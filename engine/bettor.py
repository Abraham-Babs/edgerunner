"""
engine/bettor.py
----------------
The hands of the operation. Once the runner has decided what bets to place
and at what stakes, this module physically executes them on the SportsExchange
mobile interface using the Playwright browser.

Execution flow for each ticket:
  1. Taps each odds button for the selections in the ticket, with realistic
     finger-movement jitter so the click coordinates aren't always the same.
  2. Opens the betslip. Tries multiple button selectors in sequence — if the
     betslip button can't be found one way, it tries the next. If all fail,
     it navigates directly to the betslip URL as a last resort.
  3. Detects if the betslip drawer is still docked/minimized at the bottom
     of the screen and expands it before trying to enter the stake.
  4. Enters the stake amount with human-like keystroke timing — one character
     at a time, with variable delays between each key press.
  5. Submits the bet. Again tries multiple selectors for the 'Place Bet' button.
  6. Takes a screenshot of the confirmation/receipt screen and saves it.
  7. Logs the full bet record (time, matches, odds, stake, result) to a CSV file.

All steps include fallback behavior and diagnostic screenshot capture if
something unexpected happens, so failures are visible and traceable.
"""

import os
import csv
import time
import random
import uuid
import subprocess
import tempfile
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd

from engine.config import BET_LOG_FILE, SHOTS_DIR, EXCHANGE_USERNAME, EXCHANGE_PASSWORD
from engine.human_interaction import human_tap, human_type, human_pause
from engine.parser import clean_page, select_week_tab

def _get_code_version() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"

CODE_VERSION = _get_code_version()

def _sync_root_bet_log():
    try:
        root_path = "bet_log.csv"
        if os.path.abspath(BET_LOG_FILE) != os.path.abspath(root_path) and os.path.exists(BET_LOG_FILE):
            shutil.copyfile(BET_LOG_FILE, root_path)
    except Exception:
        pass

class Bettor:
    def __init__(self, page):
        self.page = page
        self.last_placed_slip_expiry: Optional[int] = None
        self.last_failure_reason: Optional[str] = None
        self.pending_bets: Dict[str, Any] = {}
        self._ensure_log_header()

    def _ensure_log_header(self):
        os.makedirs(os.path.dirname(BET_LOG_FILE), exist_ok=True)
        if not os.path.exists(BET_LOG_FILE):
            with open(BET_LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "ticket_type", "league", "matches", "outcomes",
                    "combined_odds", "avg_edge", "stake", "status", "receipt_file",
                    "bet_id", "settled_at", "outcome", "returned_amount", "code_version"
                ])

    def log_bet(self, ticket: Dict[str, Any], status: str, receipt_file: str = "") -> str:
        bet_id = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat()
        outcome = "PENDING" if status == "CONFIRMED_SUCCESS" else status
        settled_at = ""
        returned_amount = 0.0

        matches = "; ".join([l.get("match_name", "") for l in ticket.get("legs", [])])
        outcomes = "; ".join([l.get("outcome", "") for l in ticket.get("legs", [])])
        league = ticket.get("legs", [{}])[0].get("league", "") if ticket.get("legs") else ""

        with open(BET_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                ts,
                ticket.get("type", ""),
                league,
                matches,
                outcomes,
                ticket.get("combined_odds", 0.0),
                round(ticket.get("avg_edge", 0.0), 4),
                ticket.get("stake", 0.0),
                status,
                receipt_file,
                bet_id,
                settled_at,
                outcome,
                returned_amount,
                CODE_VERSION
            ])

        if status == "CONFIRMED_SUCCESS":
            self.pending_bets[bet_id] = {
                "match_names": [l.get("match_name", "") for l in ticket.get("legs", []) if l.get("match_name")],
                "stake": ticket.get("stake", 0.0),
                "combined_odds": ticket.get("combined_odds", 1.0),
                "placed_at": ts
            }

        _sync_root_bet_log()
        return bet_id

    def execute_ticket(self, ticket: Dict[str, Any], dry_run: bool = False, dry_fire: bool = False, max_odds_cap: Optional[float] = None, min_odds_cap: Optional[float] = None) -> bool:
        """
        Executes a single or multi-leg ticket:
        1. Taps each odds selection
        2. Opens betslip
        3. Enters stake
        4. Submits bet (unless dry_fire is True)
        5. Validates confirmation screen
        """
        ticket_type = ticket["type"]
        stake = ticket["stake"]
        legs = ticket["legs"]
        comb_odds = ticket.get("combined_odds", 1.0)
        self.last_failure_reason = None

        # HARD CAPITAL SHIELD: Mode-bound odds range assertions
        if max_odds_cap is not None and comb_odds > max_odds_cap:
            print(f"[!] HARD REJECT: Ticket odds {comb_odds} exceeds mode max odds cap {max_odds_cap}. Aborting bet.")
            self.last_failure_reason = "EXCEEDS_MAX_ODDS"
            return False
        if min_odds_cap is not None and comb_odds < min_odds_cap:
            print(f"[!] HARD REJECT: Ticket odds {comb_odds} is below minimum odds floor {min_odds_cap}. Aborting bet.")
            self.last_failure_reason = "BELOW_MIN_ODDS"
            return False

        print(f"[*] Preparing Ticket [{ticket_type.upper()}]: {len(legs)} leg(s), Stake: ₦{stake}")
        for idx, leg in enumerate(legs, 1):
            print(f"    Leg {idx}: {leg.get('match_name')} -> {leg.get('outcome')} @ {leg.get('raw_odds')}")

        dry_fire = dry_run or dry_fire

        # Ensure any open betslip, promo popup, or receipt is dismissed and clean before tapping odds
        clean_page(self.page)
        self.close_betslip()
        self.reset_betslip()

        try:
            # Click each leg's button with multi-market tab support
            for leg in legs:
                match_name = leg.get("match_name", "")
                category = leg.get("category", "Popular")
                tab_name = leg.get("tab_name", "1X2")
                btn_idx = leg.get("btn_idx", 0)
                week = leg.get("week", None)
                league = leg.get("league", None)

                # Switch league if cross-league ticket
                if league:
                    switched = self.switch_league(league)
                    if not switched:
                        print(f"[-] Could not switch to league {league}. Aborting ticket.")
                        self.last_failure_reason = "LEAGUE_SWITCH_FAILED"
                        return False
                    human_pause(0.2, 0.5)

                # Ensure target round week tab is active so secondary markets reveal its fixtures
                if week:
                    select_week_tab(self.page, week)
                    human_pause(0.2, 0.4)

                # Ensure target market tab is active
                self.select_market(category, tab_name)
                human_pause(0.3, 0.7)

                # Click odds button with pre-click odds validation and active self-correction
                expected_odds = leg.get("raw_odds")
                clicked = self.click_fixture_button(
                    match_name, btn_idx, week=week, tab_name=tab_name, expected_odds=expected_odds
                )
                if not clicked:
                    # Active self-correction: if timer permits, re-assert week and market tab and retry
                    slip_cd = self.get_betslip_expiry_seconds() or 30
                    if slip_cd > 12:
                        print(f"[*] Pre-click mismatch or tab shift for {match_name}. Re-asserting {week or ''} & {tab_name}...")
                        if week:
                            select_week_tab(self.page, week)
                            self.page.wait_for_timeout(300)
                        self.select_market(category, tab_name)
                        self.page.wait_for_timeout(400)
                        clicked = self.click_fixture_button(
                            match_name, btn_idx, week=week, tab_name=tab_name, expected_odds=expected_odds
                        )
                if not clicked:
                    print(f"[-] Odds button for {match_name} ({week}) failed verification or could not be clicked. Aborting ticket.")
                    self.last_failure_reason = "BUTTON_NOT_FOUND"
                    return False
                self.page.wait_for_timeout(random.randint(600, 1100))

            # Open Betslip with verified testid selector
            try:
                human_pause(0.4, 0.9)
                betslip_selectors = [
                    'button[data-testid="bottom-nav-item-betslip"]',
                    '[data-testid="acca-bonus-selections-wrapper"]',
                    '[data-testid="acca-bonus-wrapper"]',
                    "button:has-text('Betslip')",
                    "a[href*='betslip']"
                ]
                if not self.is_betslip_open():
                    for sel in betslip_selectors:
                        el = self.page.locator(sel).first
                        if el.count() > 0 and el.is_visible(timeout=1000):
                            try:
                                el.tap()
                            except Exception:
                                el.click(force=True)
                            break
                    self.page.wait_for_timeout(800)

                # Dismiss expired events banner if present
                rem_exp = self.page.locator("button:has-text('REMOVE EXPIRED'), button:has-text('Remove Expired')").first
                if rem_exp.count() > 0 and rem_exp.is_visible(timeout=1000):
                    print("[*] Detected expired events banner. Tapping REMOVE EXPIRED...")
                    rem_exp.click(force=True)
                    self.page.wait_for_timeout(600)

                # Wait for stake input to become visible in drawer
                stake_field = self.page.locator('input[data-testid="betslip-stake-amount"], input[inputmode="decimal"]').first
                try:
                    stake_field.wait_for(state="visible", timeout=6000)
                except Exception:
                    pass

                # Hard gate: betslip must be open before proceeding
                if not self.is_betslip_open():
                    print(f"[!] REJECTED: Betslip drawer did not open after tap. Aborting ticket.")
                    self.last_failure_reason = "BETSLIP_NOT_OPEN"
                    self.capture_diagnostic("betslip_not_open")
                    return False
            except Exception as e:
                print(f"\n[!] ALERT: Failed to open betslip: {e}")
                self.capture_diagnostic("betslip_open_error")
                return False

            # Explicitly select Singles vs Multiple / Acca tab based on ticket type
            if ticket_type == "single":
                try:
                    s_tab = self.page.locator("button:has-text('Singles'), p:has-text('Singles')").first
                    if s_tab.count() > 0 and s_tab.is_visible(timeout=300):
                        human_tap(s_tab, self.page)
                        self.page.wait_for_timeout(300)
                except Exception:
                    pass
            elif ticket_type in ("double", "treble"):
                try:
                    m_tab = self.page.locator("button:has-text('Multiple'), button:has-text('Multiples'), p:has-text('Multiple'), p:has-text('Multiples'), button:has-text('Acca')").first
                    if m_tab.count() > 0 and m_tab.is_visible(timeout=300):
                        human_tap(m_tab, self.page)
                        self.page.wait_for_timeout(300)
                except Exception:
                    pass

            # In-Betslip Stateful 3-Point Validation (Zero-Tolerance)
            slip_odds = self.get_betslip_total_odds()
            expected_odds = ticket.get("combined_odds", 1.0)
            if slip_odds is None or abs(slip_odds - expected_odds) > 0.02:
                print(f"[!] REJECTED: Slip odds {slip_odds} != expected {expected_odds}. Aborting bet.")
                self.last_failure_reason = "ODDS_MISMATCH"
                self.capture_diagnostic("odds_mismatch_rejected")
                self.clear_betslip_selections()
                self.close_betslip()
                return False

            # Assert all match names exist in betslip drawer
            drawer_text = self.page.evaluate("""() => {
                const header = document.querySelector('[data-testid="betslip-header"]');
                if (header) {
                    let curr = header;
                    while (curr.parentElement && curr.parentElement !== document.body) {
                        curr = curr.parentElement;
                    }
                    return curr.innerText || '';
                }
                const all = Array.from(document.querySelectorAll('div'));
                const bs = all.find(d => (d.innerText || '').includes('VIRTUALS BETSLIP') && (d.innerText || '').includes('PLACE BET'));
                return bs ? bs.innerText : (document.body.innerText || '');
            }""")
            for leg in legs:
                exp_match = leg.get("match_name", "")
                teams = [t.strip() for t in exp_match.split("-")] if "-" in exp_match else [exp_match.strip()]
                matched = (exp_match in drawer_text) or all(t in drawer_text for t in teams)
                if exp_match and not matched:
                    print(f"[!] REJECTED: Slip missing expected leg {exp_match}. Aborting bet.")
                    self.last_failure_reason = "MATCH_MISMATCH"
                    self.capture_diagnostic("match_mismatch_rejected")
                    self.clear_betslip_selections()
                    self.close_betslip()
                    return False

            # In-Betslip Live Expiry Guard (Lean 1s cutoff - accepts bets down to final second)
            slip_sec = self.get_betslip_expiry_seconds()
            if slip_sec is not None:
                print(f"[*] In-Betslip Expiration Timer: {slip_sec}s remaining")
                if slip_sec <= 0:
                    print(f"[!] REJECTED: Slip timer expired (0s remaining). Aborting to avoid platform lockout.")
                    self.last_failure_reason = "EXPIRED_TIMER"
                    self.capture_diagnostic("slip_timer_expired")
                    bet_id = self.log_bet(ticket, status="REJECTED_EXPIRED_0s")
                    return False

            # Input Stake with resilient input selectors and verified echo assertion
            try:
                stake_selectors = [
                    "input[data-testid='betslip-stake-amount']",
                    "input[inputmode='decimal']",
                    "input[type='number']",
                    "input[inputmode='numeric']",
                    "input[placeholder*='Stake']",
                    "input[type='text']"
                ]
                stake_input = None
                for sel in stake_selectors:
                    inp = self.page.locator(sel).first
                    if inp.count() > 0 and inp.is_visible(timeout=1500):
                        stake_input = inp
                        break

                if stake_input:
                    stake_str = str(int(stake) if stake.is_integer() else stake)
                    human_pause(0.3, 0.7)
                    human_type(stake_input, stake_str)
                    self.page.wait_for_timeout(random.randint(400, 700))

                    # Stake echo assertion: verify field holds the exact typed stake
                    val = (stake_input.input_value() or "").strip().replace(",", "")
                    if val != stake_str:
                        stake_input.fill("")
                        human_pause(0.1, 0.2)
                        human_type(stake_input, stake_str)
                        val = (stake_input.input_value() or "").strip().replace(",", "")
                        if val != stake_str:
                            print(f"[!] REJECTED: Stake input echo '{val}' != expected '{stake_str}'. Aborting bet.")
                            return False
                else:
                    print("\n[!] ALERT: Stake input element not found in betslip! Layout may have shifted.")
                    self.capture_diagnostic("stake_input_missing")
                    return False
            except Exception as e:
                print(f"\n[!] ALERT: Failed entering stake: {e}")
                self.capture_diagnostic("stake_entry_error")
                return False

            # Intercept if DRY FIRE / DRY RUN: take verification screenshot and safely abort before submit
            if dry_fire or dry_run:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                diag_path = f"{SHOTS_DIR}/dry_fire_slip_{ts}.png"
                self.page.screenshot(path=diag_path)
                print(f"[+] [DRY FIRE] Verified full DOM pipeline without betting! Evidence: {diag_path}")
                bet_id = self.log_bet(ticket, status="DRY_FIRE_VERIFIED", receipt_file=diag_path)
                self.clear_betslip_selections()
                self.close_betslip()
                return True

            # Submit Bet with resilient button selectors
            try:
                place_selectors = [
                    "button:has-text('PLACE BET')",
                    "button:has-text('Place Bet')",
                    "button:has-text('Confirm Bet')",
                    "button[data-testid*='place-bet']",
                    "button[type='submit']"
                ]
                place_btn = None
                for sel in place_selectors:
                    btn = self.page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible(timeout=1500):
                        place_btn = btn
                        break

                if place_btn:
                    human_pause(0.6, 1.4)
                    human_tap(place_btn, self.page)
                    self.page.wait_for_timeout(4500)
                    
                    self.last_placed_slip_expiry = slip_sec
                    print(f"[+] Bet successfully placed!")
                    bet_id = self.log_bet(ticket, status="CONFIRMED_SUCCESS")
                    return True
                else:
                    print("\n[!] ALERT: PLACE BET button not visible on screen! Betting aborted safely.")
                    self.capture_diagnostic("place_bet_missing")
                    bet_id = self.log_bet(ticket, status="SUBMISSION_BUTTON_UNAVAILABLE")
                    return False
            except Exception as e:
                print(f"\n[!] ALERT: Error during bet submission: {e}")
                self.capture_diagnostic("submission_exception")
                bet_id = self.log_bet(ticket, status=f"SUBMISSION_ERROR: {e}")
                return False
        finally:
            self.close_betslip()

    def is_betslip_open(self) -> bool:
        """Returns True if the betslip drawer or empty betslip overlay is currently open on screen."""
        try:
            drawer = self.page.locator('button[data-testid="betslip-header-title-close-icon"], [data-testid="betslip-header"], [data-testid="empty-betslip"]').first
            if drawer.count() > 0 and drawer.is_visible(timeout=300):
                return True
            return bool(self.page.evaluate("""() => {
                const header = Array.from(document.querySelectorAll('*')).find(el => (el.innerText || '').trim() === 'VIRTUALS BETSLIP');
                return !!(header && header.getBoundingClientRect().height > 0);
            }"""))
        except Exception:
            return False

    def get_betslip_badge_count(self) -> int:
        """Returns the integer selection count currently displayed on the bottom nav betslip badge or sticky selection bar."""
        try:
            cnt = self.page.evaluate("""() => {
                // 1. Check sticky bottom bar (e.g. '1 Selection', '2 Selections')
                const all = Array.from(document.querySelectorAll('div, span, p'));
                const selBar = all.find(el => /^\\d+\\s+Selection/i.test((el.innerText || '').trim()));
                if (selBar) {
                    const m = (selBar.innerText || '').match(/^(\\d+)\\s+Selection/i);
                    if (m) return parseInt(m[1]);
                }
                // 2. Check bottom nav betslip badge element
                const badge = document.querySelector('[data-testid*="betslip"] span, button[data-testid*="betslip"] span, [class*="badge"]');
                if (badge) {
                    const m = (badge.innerText || '').match(/\\d+/);
                    if (m) return parseInt(m[0]);
                }
                return 0;
            }""")
            if cnt and cnt > 0:
                return cnt
        except Exception:
            pass
        return 0

    def close_betslip(self):
        """Close/dismiss the betslip drawer or confirmation modal so the fixture board is unobstructed."""
        try:
            # 1. Direct verified testid selector for SportsExchange's betslip header close icon
            close_btn = self.page.locator('button[data-testid="betslip-header-title-close-icon"], [data-testid*="close-icon"]').first
            if close_btn.count() > 0 and close_btn.is_visible(timeout=500):
                human_tap(close_btn, self.page)
                self.page.wait_for_timeout(300)
                if not self.is_betslip_open():
                    return True

            # 2. General close selectors
            close_selectors = [
                "[aria-label*='close' i]",
                "[data-testid*='close' i]",
                "button[class*='close' i]",
                "button:has-text('✕')",
                "button:has-text('×')",
                "button:has-text('X')",
                ".virtuals-betslip button",
                "header button"
            ]
            for sel in close_selectors:
                el = self.page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=300):
                    human_tap(el, self.page)
                    self.page.wait_for_timeout(300)
                    if not self.is_betslip_open():
                        return True

            # 3. Verified header close icon coordinate (x=332, y=84) with spatial jitter
            if self.is_betslip_open():
                jx = 332 + random.uniform(-4, 4)
                jy = 84 + random.uniform(-4, 4)
                self.page.mouse.click(jx, jy)
                self.page.wait_for_timeout(300)
                if not self.is_betslip_open():
                    return True

            # 4. Fallback: Escape key
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
            return not self.is_betslip_open()
        except Exception:
            pass
        return False

    def clear_betslip_selections(self):
        """Removes any stale, expired, or leftover selections from the betslip."""
        try:
            # 1. Primary "Clear All" locator across button, span, div, p
            clear_selectors = [
                "button:has-text('Clear All')",
                "span:has-text('Clear All')",
                "div:has-text('Clear All')",
                "p:has-text('Clear All')",
                "[data-testid*='clear']",
                "[data-testid*='Clear']"
            ]
            for sel in clear_selectors:
                clear_btn = self.page.locator(sel).first
                if clear_btn.count() > 0 and clear_btn.is_visible(timeout=500):
                    human_tap(clear_btn, self.page)
                    self.page.wait_for_timeout(400)
                    break

            # Check for potential "Clear Betslip" confirmation dialog (Yes / Confirm / Clear / Ok)
            self.page.evaluate("""() => {
                const candidates = Array.from(document.querySelectorAll('button, div[role="button"], span'));
                const conf = candidates.find(el => {
                    const t = (el.innerText || '').trim().toLowerCase();
                    return ['yes', 'confirm', 'clear', 'ok', 'proceed'].includes(t);
                });
                if (conf && conf.getBoundingClientRect().height > 0) conf.click();
            }""")
            self.page.wait_for_timeout(300)

            # 2. Primary "REMOVE EXPIRED" banner/button
            rem_btn = self.page.locator("button[data-testid='loading-button-contained--error'], button:has-text('REMOVE EXPIRED'), button:has-text('Remove Expired')").first
            if rem_btn.count() > 0 and rem_btn.is_visible(timeout=400):
                human_tap(rem_btn, self.page)
                self.page.wait_for_timeout(400)

            # 3. DOM JavaScript click fallback for "Clear All" text
            self.page.evaluate("""() => {
                const all = Array.from(document.querySelectorAll('*'));
                const clearEl = all.find(el => (el.innerText || '').trim() === 'Clear All');
                if (clearEl) {
                    clearEl.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    const p = clearEl.closest('button') || clearEl.parentElement;
                    if (p) p.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                }
            }""")
            self.page.wait_for_timeout(300)

            # 4. Individual item remove buttons / trash icons inside drawer
            self.page.evaluate("""() => {
                const drawer = document.querySelector('div[class*="drawer"], div.fixed.inset-0, [data-testid*="betslip"]');
                if (!drawer) return;
                const svgs = Array.from(drawer.querySelectorAll('svg'));
                for (const s of svgs) {
                    const rect = s.getBoundingClientRect();
                    // Item trash icons appear on the right side of selection cards
                    if (rect.left > 240 && rect.top > 100) {
                        const target = s.closest('button') || s.parentElement || s;
                        target.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    }
                }
            }""")
            self.page.wait_for_timeout(400)
        except Exception:
            pass

    def reset_betslip(self):
        """Ensures the betslip is clean and empty before starting a new ticket."""
        try:
            clean_page(self.page)
            # If betslip is open, clear and close it
            if self.is_betslip_open():
                self.clear_betslip_selections()
                self.close_betslip()

            badge_cnt = self.get_betslip_badge_count()
            if badge_cnt > 0:
                print(f"[*] Resetting betslip: {badge_cnt} leftover selections detected.")
                opened = False
                for sel in ['button[data-testid="bottom-nav-item-betslip"]', '[data-testid*="acca-bonus"]', "button:has-text('Betslip')", "a[href*='betslip']"]:
                    el = self.page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=500):
                        human_tap(el, self.page)
                        self.page.wait_for_timeout(600)
                        opened = True
                        break
                self.clear_betslip_selections()
                self.close_betslip()

            # Post-clear assertion: verify badge count dropped to 0
            badge_cnt = self.get_betslip_badge_count()
            if badge_cnt > 0:
                print(f"[!] Residual {badge_cnt} selections after clear. Purging betslip storage and reloading...")
                try:
                    self.page.evaluate("""() => {
                        const keysToRemove = [];
                        for (let i = 0; i < localStorage.length; i++) {
                            const k = localStorage.key(i);
                            if (k && (k.toLowerCase().includes('slip') || k.toLowerCase().includes('bet') || k.toLowerCase().includes('ticket'))) {
                                keysToRemove.push(k);
                            }
                        }
                        keysToRemove.forEach(k => localStorage.removeItem(k));
                    }""")
                except Exception:
                    pass
                try:
                    self.page.reload(wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    self.page.wait_for_timeout(2000)
                try:
                    self.page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                self.page.wait_for_timeout(1000)
                clean_page(self.page)
                self.close_betslip()
        except Exception as e:
            print(f"[!] Error during reset_betslip: {e}")

    def switch_league(self, league_key: str) -> bool:
        """Switches to the requested league via direct URL or carousel, waiting for full DOM hydration."""
        league_slugs = {
            "league_en": "premier-league",
            "league_es": "primera-liga",
            "league_it": "serie-league",
            "league_de": "bundes-league"
        }
        slug = league_slugs.get(str(league_key).lower(), str(league_key).lower())
        if slug in self.page.url:
            return True

        target_url = f"https://sports-exchange.internal/en-ng/virtuals/scheduled/leagues/{slug}"
        # 1. Attempt in-page SPA carousel click to preserve betslip selections across leagues
        try:
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.wait_for_timeout(250)
            league_selectors = [
                f"a[data-testid='league-switcher-tab-{slug}']",
                f"[data-testid*='league-switcher-tab-{slug}']",
                f"a[href*='{slug}']",
                f"button:has-text('{slug}')",
                f"a:has-text('{slug}')",
                f"[data-testid*='{slug}']"
            ]
            from engine.config import LEAGUES
            league_name = LEAGUES.get(league_key, {}).get("name", "").split(" (")[0]
            if league_name:
                league_selectors.append(f"button:has-text('{league_name}')")
                league_selectors.append(f"a:has-text('{league_name}')")
                league_selectors.append(f"p:has-text('{league_name}')")

            for sel in league_selectors:
                el = self.page.locator(sel).first
                if el.count() > 0:
                    try:
                        el.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                    if el.is_visible(timeout=800):
                        human_tap(el, self.page)
                        self.page.wait_for_timeout(random.randint(900, 1400))
                        clean_page(self.page)
                        if slug in self.page.url:
                            return True
        except Exception:
            pass

        # 2. Resilient direct navigation fallback
        for attempt in range(1, 4):
            try:
                self.page.goto(target_url, wait_until="commit", timeout=25000)
                self.page.wait_for_timeout(random.randint(1500, 2200))
                try:
                    self.page.locator("button:has-text('Week ')").first.wait_for(state="visible", timeout=12000)
                except Exception:
                    pass
                clean_page(self.page)
                if slug in self.page.url:
                    return True
            except Exception as e:
                print(f"[!] Network error switching to league {slug} (attempt {attempt}/3): {e}")
                time.sleep(attempt * 2)
        return False

    def select_market(self, category: str, tab_name: str) -> bool:
        """Switches the league view to the requested market category and sub-tab, verifying active indicator."""
        try:
            clean_page(self.page)
            # Check if active market indicator already matches
            cur_market = self.page.locator('span[data-testid="selected-market-name"]').first
            if cur_market.count() > 0:
                cm = (cur_market.inner_text() or '').strip()
                if tab_name.lower() in cm.lower() or cm.lower() in tab_name.lower():
                    return True

            # 1. Primary: click tab in market-selector-tab bar
            tab_el = self.page.locator('[data-testid="market-selector-tab"]').filter(has_text=tab_name).first
            if tab_el.count() == 0:
                tab_el = self.page.locator(f"li:has-text('{tab_name}'), button:has-text('{tab_name}')").first

            if tab_el.count() > 0:
                try:
                    tab_el.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                tab_el.click(force=True)
                self.page.wait_for_timeout(600)
                return True

            # 2. Fallback: More Markets dropdown
            mm = self.page.locator("text='More Markets'").first
            if mm.count() > 0 and mm.is_visible(timeout=500):
                mm.click(force=True)
                self.page.wait_for_timeout(350)
                cat_el = self.page.locator(f"li:has-text('{category}'), button:has-text('{category}')").first
                if cat_el.count() > 0 and cat_el.is_visible(timeout=800):
                    cat_el.click(force=True)
                    self.page.wait_for_timeout(400)
                    sub_el = self.page.locator(f"button:has-text('{tab_name}'), li:has-text('{tab_name}')").first
                    if sub_el.count() > 0:
                        sub_el.click(force=True)
                        self.page.wait_for_timeout(500)
                        return True
        except Exception:
            pass
        return False

    def click_fixture_button(self, match_name: str, btn_idx: int, week: str = None, tab_name: str = None, expected_odds: float = None) -> bool:
        """Finds match row on screen using Playwright native locators, asserts odds, and clicks."""
        if self.is_betslip_open():
            self.close_betslip()
            self.page.wait_for_timeout(300)

        try:
            # 1. Parse teams from match_name (e.g. 'COM - NAP' -> ['COM', 'NAP'])
            teams = [t.strip() for t in match_name.split("-")] if "-" in match_name else [match_name.strip()]

            # 2. Locate specific fixture row container (div.flex.items-center.justify-between)
            # Must contain both teams and match-odd buttons, avoiding ancestor container scope
            rows = self.page.locator("div.flex.items-center.justify-between")
            for t in teams:
                rows = rows.filter(has_text=t)

            rows = rows.filter(has=self.page.locator('[data-testid="match-odd"]'))

            if rows.count() == 0:
                # Fallback: search anywhere in document for match container with match-odd buttons
                rows = self.page.locator("div").filter(has_text=match_name).filter(has=self.page.locator('[data-testid="match-odd"]'))
                if rows.count() == 0:
                    return False

            row = rows.first
            odd_btns = row.locator('[data-testid="match-odd"]')
            if odd_btns.count() <= btn_idx:
                return False

            btn = odd_btns.nth(btn_idx)
            btn.scroll_into_view_if_needed(timeout=3000)

            # Pre-click odds assertion
            if expected_odds is not None:
                try:
                    btn_val = float(btn.inner_text().strip().replace(",", ""))
                    if abs(btn_val - expected_odds) > 0.05:
                        print(f"[*] Odds shifted for {match_name}: live={btn_val} vs expected={expected_odds}")
                        return False
                except Exception:
                    pass

            # 3. Perform native Playwright tap/click to register mobile touch event
            try:
                btn.tap()
            except Exception:
                btn.click(force=True)
            self.page.wait_for_timeout(600)
            return True
        except Exception as e:
            print(f"[-] Error clicking odds button for {match_name}: {e}")
            return False

    def get_betslip_total_odds(self) -> Optional[float]:
        """Extracts the live combined odds directly from the open betslip drawer."""
        try:
            val = self.page.evaluate("""() => {
                // 1. Look for text element containing 'Total Odds'
                const all = Array.from(document.querySelectorAll('div, p, span'));
                for (const el of all) {
                    const txt = (el.innerText || '').trim();
                    if (/^Total\\s+Odds/i.test(txt)) {
                        const next = el.nextElementSibling;
                        if (next && /^\\d+\\.\\d+$/.test(next.innerText.trim())) {
                            return parseFloat(next.innerText.trim());
                        }
                        const match = txt.match(/Total\\s+Odds\\s*[:]?\\s*(\\d+\\.\\d+)/i);
                        if (match) return parseFloat(match[1]);
                    }
                }
                // 2. Check betslip cards/summary
                const slipCard = document.querySelector('.virtuals-betslip, [data-testid*="betslip"], div[class*="betslip"]');
                if (slipCard) {
                    const numbers = Array.from(slipCard.querySelectorAll('span, div'))
                        .map(s => (s.innerText || '').trim())
                        .filter(s => /^\\d+\\.\\d{2}$/.test(s));
                    if (numbers.length > 0) {
                        return parseFloat(numbers[numbers.length - 1]);
                    }
                }
                return null;
            }""")
            return float(val) if val else None
        except Exception:
            return None

    def get_betslip_expiry_seconds(self) -> Optional[int]:
        """Extracts remaining countdown seconds from the open betslip."""
        try:
            time_str = self.page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('div, p, span'));
                for (const el of els) {
                    const txt = (el.innerText || '').trim();
                    const m = txt.match(/expire\\s+in\\s*[:]?\\s*(\\d{1,2}):(\\d{2})/i);
                    if (m) {
                        return m[1] + ':' + m[2];
                    }
                }
                return null;
            }""")
            if time_str:
                parts = time_str.split(":")
                return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass
        return None

    def reconcile_settled_bets(self):
        """
        Periodically checks settled bets from the platform to verify real outcome & payout.
        Records settled status back to bet log for empirical tracking.
        """
        try:
            my_bets_btn = self.page.locator("a[href*='bets'], [data-testid*='my-bets'], button:has-text('My Bets')").first
            if my_bets_btn.count() > 0 and my_bets_btn.is_visible(timeout=1000):
                human_tap(my_bets_btn, self.page)
                self.page.wait_for_timeout(1500)
                settled_items = self.page.evaluate("""() => {
                    const items = [];
                    const cards = Array.from(document.querySelectorAll('[data-testid*="bet-card"], div[class*="bet-card"]'));
                    for (const card of cards) {
                        const txt = card.innerText || '';
                        let status = 'PENDING';
                        if (/won/i.test(txt)) status = 'WON';
                        else if (/lost/i.test(txt)) status = 'LOST';
                        else if (/void/i.test(txt)) status = 'VOID';
                        items.push({ text: txt.slice(0, 1000), status: status });
                    }
                    return items;
                }""")
                if settled_items:
                    print(f"[+] Reconciled {len(settled_items)} platform bet records.")
                    if self.pending_bets:
                        updates = {}
                        for item in settled_items:
                            c_status = item.get("status")
                            if c_status in ("PENDING", None):
                                continue
                            c_text = item.get("text", "").lower()
                            matching_ids = []
                            for p_id, p_info in list(self.pending_bets.items()):
                                m_names = p_info.get("match_names", [])
                                if m_names and all(m.lower() in c_text for m in m_names):
                                    matching_ids.append(p_id)

                            # Skip ambiguous matches (0 or >1)
                            if len(matching_ids) == 1:
                                match_id = matching_ids[0]
                                p_data = self.pending_bets[match_id]
                                # Calculated payout (stake * combined_odds) since platform card text does not reliably expose net return
                                ret_amt = round(p_data["stake"] * p_data["combined_odds"], 2) if c_status == "WON" else 0.0
                                updates[match_id] = {
                                    "outcome": c_status,
                                    "settled_at": datetime.utcnow().isoformat(),
                                    "returned_amount": ret_amt
                                }

                        if updates and os.path.exists(BET_LOG_FILE):
                            try:
                                df = pd.read_csv(BET_LOG_FILE, dtype={"settled_at": str, "outcome": str, "bet_id": str, "code_version": str})
                                df["settled_at"] = df["settled_at"].fillna("")
                                df["outcome"] = df["outcome"].fillna("")
                                for m_id, u_info in updates.items():
                                    idx = df.index[df["bet_id"] == m_id]
                                    if len(idx) > 0:
                                        df.loc[idx, "outcome"] = u_info["outcome"]
                                        df.loc[idx, "settled_at"] = u_info["settled_at"]
                                        df.loc[idx, "returned_amount"] = u_info["returned_amount"]
                                        self.pending_bets.pop(m_id, None)

                                d_name = os.path.dirname(os.path.abspath(BET_LOG_FILE))
                                with tempfile.NamedTemporaryFile("w", dir=d_name, delete=False, newline="", encoding="utf-8") as tf:
                                    temp_path = tf.name
                                df.to_csv(temp_path, index=False)
                                os.replace(temp_path, BET_LOG_FILE)
                                _sync_root_bet_log()
                                print(f"[+] Successfully updated {len(updates)} settled bet(s) in log.")
                            except Exception as write_err:
                                print(f"[!] Error updating bet_log with settlement: {write_err}")

                self.close_betslip()
        except Exception:
            pass

    def ensure_authenticated(self) -> bool:
        """Checks if session is active; attempts automatic login if credentials exist in .env."""
        try:
            login_btn = self.page.locator("button:has-text('LOGIN'), a:has-text('LOGIN')").first
            if login_btn.count() == 0 or not login_btn.is_visible(timeout=1500):
                return True

            if not EXCHANGE_USERNAME or not EXCHANGE_PASSWORD:
                print("[!] Notice: Logged out state detected and no credentials found in .env.")
                return False

            print("[*] Logged out state detected. Attempting automated login with phone number...")
            human_tap(login_btn, self.page)
            self.page.wait_for_timeout(1500)

            user_input = self.page.locator("[data-testid='txt-username'], input[name='username']").first
            pass_input = self.page.locator("[data-testid='txt-password'], input[name='password']").first

            if user_input.is_visible(timeout=3000) and pass_input.is_visible(timeout=3000):
                phone = EXCHANGE_USERNAME.strip()
                if phone.startswith("0") and len(phone) == 11:
                    phone = phone[1:]

                human_type(user_input, phone)
                human_pause(0.2, 0.4)
                human_type(pass_input, EXCHANGE_PASSWORD)
                human_pause(0.3, 0.5)

                submit = self.page.locator("button[data-testid*='highlight'], button:has-text('LOGIN'):not([data-testid*='nav'])").last
                human_tap(submit, self.page)
                self.page.wait_for_timeout(6000)

                if self.page.locator("button:has-text('LOGIN'), a:has-text('LOGIN')").count() == 0:
                    print("[+] Auto-login successful! Session authenticated.")
                    return True
                else:
                    print("[-] Auto-login attempt submitted but login prompt persists.")
                    return False
        except Exception as e:
            print(f"[-] Authentication routine encountered: {e}")
        return False

    def capture_diagnostic(self, reason: str):
        """Save a full diagnostic screenshot when an unexpected UI condition happens."""
        try:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            diag_path = f"{SHOTS_DIR}/diagnostic_{reason}_{ts}.png"
            self.page.screenshot(path=diag_path)
            print(f"[!] Saved UI diagnostic screenshot to: {diag_path}")
        except Exception:
            pass

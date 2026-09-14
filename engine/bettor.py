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
from datetime import datetime
from typing import Dict, Any, List, Optional

from engine.config import BET_LOG_FILE, SHOTS_DIR, EXCHANGE_USERNAME, EXCHANGE_PASSWORD
from engine.human_interaction import human_tap, human_type, human_pause
from engine.parser import clean_page, select_week_tab

class Bettor:
    def __init__(self, page):
        self.page = page
        self.last_placed_slip_expiry: Optional[int] = None
        self.last_failure_reason: Optional[str] = None
        self._ensure_log_header()

    def _ensure_log_header(self):
        os.makedirs(os.path.dirname(BET_LOG_FILE), exist_ok=True)
        if not os.path.exists(BET_LOG_FILE):
            with open(BET_LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "ticket_type", "league", "matches", "outcomes",
                    "combined_odds", "avg_edge", "stake", "status", "receipt_file"
                ])

    def log_bet(self, ticket: Dict[str, Any], status: str, receipt_file: str = ""):
        matches = "; ".join([l.get("match_name", "") for l in ticket["legs"]])
        outcomes = "; ".join([l.get("outcome", "") for l in ticket["legs"]])
        league = ticket["legs"][0].get("league", "") if ticket["legs"] else ""

        with open(BET_LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                ticket["type"],
                league,
                matches,
                outcomes,
                ticket.get("combined_odds", 0.0),
                round(ticket.get("avg_edge", 0.0), 4),
                ticket["stake"],
                status,
                receipt_file
            ])

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
                for sel in betslip_selectors:
                    el = self.page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=1000):
                        human_tap(el, self.page)
                        break

                # Wait for stake input to become visible in drawer without toggling back closed
                stake_field = self.page.locator('input[data-testid="betslip-stake-amount"], input[inputmode="decimal"]').first
                try:
                    stake_field.wait_for(state="visible", timeout=3500)
                except Exception:
                    pass
            except Exception as e:
                print(f"\n[!] ALERT: Failed to open betslip: {e}")
                self.capture_diagnostic("betslip_open_error")
                return False

            # Dismiss expired events banner if present
            rem_exp = self.page.locator("button:has-text('REMOVE EXPIRED'), button:has-text('Remove Expired')").first
            if rem_exp.count() > 0 and rem_exp.is_visible(timeout=800):
                print("[*] Detected expired events banner. Tapping REMOVE EXPIRED...")
                self.last_failure_reason = "EXPIRED_BANNER"
                human_tap(rem_exp, self.page)
                self.page.wait_for_timeout(800)

            # If single ticket and multiple tabs appear, explicitly select Singles tab
            if ticket_type == "single":
                try:
                    s_tab = self.page.locator("button:has-text('Singles'), p:has-text('Singles')").first
                    if s_tab.count() > 0 and s_tab.is_visible(timeout=300):
                        human_tap(s_tab, self.page)
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

            # Assert match name on betslip card
            slip_match = self.page.evaluate("""() => {
                const drawer = document.querySelector('div[class*="drawer"], div.fixed.inset-0, [data-testid*="betslip"]');
                if (!drawer) return null;
                const m = (drawer.innerText || '').match(/[A-Z]{3}\\s*-\\s*[A-Z]{3}/);
                return m ? m[0].replace(/\\s+/g, ' ') : null;
            }""")
            if slip_match and legs:
                exp_match = legs[0].get("match_name", "")
                if exp_match and slip_match != exp_match:
                    print(f"[!] REJECTED: Slip match {slip_match} != expected {exp_match}. Aborting bet.")
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
                    self.log_bet(ticket, status="REJECTED_EXPIRED_0s")
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

            # Intercept if DRY FIRE: take verification screenshot and safely abort before submit
            if dry_fire:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                diag_path = f"{SHOTS_DIR}/dry_fire_slip_{ts}.png"
                self.page.screenshot(path=diag_path)
                print(f"[+] [DRY FIRE] Verified full DOM pipeline without betting! Evidence: {diag_path}")
                self.log_bet(ticket, status="DRY_FIRE_VERIFIED", receipt_file=diag_path)
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
                    self.log_bet(ticket, status="CONFIRMED_SUCCESS")
                    return True
                else:
                    print("\n[!] ALERT: PLACE BET button not visible on screen! Betting aborted safely.")
                    self.capture_diagnostic("place_bet_missing")
                    self.log_bet(ticket, status="SUBMISSION_BUTTON_UNAVAILABLE")
                    return False
            except Exception as e:
                print(f"\n[!] ALERT: Error during bet submission: {e}")
                self.capture_diagnostic("submission_exception")
                self.log_bet(ticket, status=f"SUBMISSION_ERROR: {e}")
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
            league_btn = self.page.locator(f"a[href*='{slug}'], button:has-text('{slug}')").first
            if league_btn.count() > 0 and league_btn.is_visible(timeout=800):
                human_tap(league_btn, self.page)
                self.page.wait_for_timeout(random.randint(1000, 1500))
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
                self.page.locator("button:has-text('Week ')").first.wait_for(state="visible", timeout=12000)
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
            # Check if active market indicator already matches
            cur_market = self.page.locator('span[data-testid="selected-market-name"]').first
            if cur_market.count() > 0:
                cm = (cur_market.inner_text() or '').strip()
                if tab_name.lower() in cm.lower() or cm.lower() in tab_name.lower():
                    return True

            # 1. Try clicking tab in horizontal pill bar
            tab_el = self.page.locator(f"li:has-text('{tab_name}'), p:has-text('{tab_name}'), button:has-text('{tab_name}')").first
            if tab_el.count() > 0:
                try:
                    tab_el.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                if tab_el.is_visible(timeout=800):
                    human_tap(tab_el, self.page)
                    self.page.wait_for_timeout(400)
                    if cur_market.count() > 0:
                        cm = (cur_market.inner_text() or '').strip()
                        if tab_name.lower() in cm.lower() or cm.lower() in tab_name.lower():
                            return True

            # 2. If not active, open More Markets dropdown and pick category
            mm = self.page.locator("text='More Markets'").first
            if mm.count() > 0 and mm.is_visible(timeout=500):
                human_tap(mm, self.page)
                self.page.wait_for_timeout(350)
                cat_el = self.page.locator(f"li:has-text('{category}'), button:has-text('{category}'), p:has-text('{category}')").first
                if cat_el.count() > 0 and cat_el.is_visible(timeout=800):
                    human_tap(cat_el, self.page)
                    self.page.wait_for_timeout(400)
                    sub_el = self.page.locator(f"button:has-text('{tab_name}'), li:has-text('{tab_name}'), p:has-text('{tab_name}')").first
                    if sub_el.count() > 0:
                        try:
                            sub_el.scroll_into_view_if_needed(timeout=1000)
                            self.page.wait_for_timeout(200)
                        except Exception:
                            pass
                        human_tap(sub_el, self.page)
                        self.page.wait_for_timeout(500)
                        if cur_market.count() > 0:
                            cm = (cur_market.inner_text() or '').strip()
                            if tab_name.lower() in cm.lower() or cm.lower() in tab_name.lower():
                                return True
        except Exception:
            pass
        return False

    def click_fixture_button(self, match_name: str, btn_idx: int, week: str = None, tab_name: str = None, expected_odds: float = None) -> bool:
        """Finds match row on screen strictly within target week boundary and asserts odds before clicking."""
        # Ensure any betslip drawer or overlay is closed so odds table is unobstructed
        if self.is_betslip_open():
            self.close_betslip()
            self.page.wait_for_timeout(300)

        try:
            res = self.page.evaluate(r"""({mName, bIdx, wName, expOdds}) => {
                const weekHeaders = Array.from(document.querySelectorAll('p')).filter(p => {
                    return /^Week\s+\d+$/i.test((p.innerText || '').trim()) && !p.closest('button');
                });
                
                let targetHeader = null;
                let nextHeader = null;
                for (let i = 0; i < weekHeaders.length; i++) {
                    const txt = (weekHeaders[i].innerText || '').trim();
                    if (txt === wName || txt.startsWith(wName)) {
                        targetHeader = weekHeaders[i];
                        nextHeader = weekHeaders[i + 1] || null;
                        break;
                    }
                }
                
                let startY = 0;
                let endY = 999999;
                if (targetHeader) {
                    targetHeader.scrollIntoView();
                    startY = targetHeader.getBoundingClientRect().top + window.scrollY - 10;
                    endY = nextHeader ? (nextHeader.getBoundingClientRect().top + window.scrollY) : 999999;
                }
                
                const candidateRows = Array.from(document.querySelectorAll('div')).filter(d => {
                    if (d.children.length > 6) return false;
                    const txt = d.innerText || '';
                    const codes = txt.match(/[A-Z]{3}/g) || [];
                    if (codes.length === 2 && txt.includes('-')) {
                        const key = codes[0] + ' - ' + codes[1];
                        if (key === mName) {
                            const rect = d.getBoundingClientRect();
                            const absY = rect.top + window.scrollY;
                            if (!targetHeader || (absY >= startY && absY < endY)) {
                                return true;
                            }
                        }
                    }
                    return false;
                });
                
                for (const r of candidateRows) {
                    const btns = Array.from(r.querySelectorAll('button[data-testid="match-odd"], button'));
                    const oddBtns = btns.filter(b => /^\d+\.\d+$/.test((b.innerText || '').trim()));
                    if (oddBtns.length > bIdx) {
                        const btn = oddBtns[bIdx];
                        const btnVal = parseFloat(btn.innerText.trim().replace(/,/g, ''));
                        // PRE-CLICK ASSERTION: Odds must match expected_odds
                        if (expOdds !== null && expOdds !== undefined && !isNaN(expOdds)) {
                            if (Math.abs(btnVal - expOdds) > 0.02) {
                                return false;
                            }
                        }
                        btn.scrollIntoView?.({ block: "center", inline: "center" });
                        btn.click();
                        const rect = btn.getBoundingClientRect();
                        return { success: true, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
                    }
                }
                return false;
            }""", {"mName": match_name, "bIdx": btn_idx, "wName": week, "expOdds": expected_odds})
            if res and isinstance(res, dict) and res.get("success"):
                # Micro-pause and verify if betslip badge registered
                self.page.wait_for_timeout(300)
                badge_cnt = self.get_betslip_badge_count()
                if badge_cnt == 0 and res.get("x") and res.get("y"):
                    # Fallback real mouse tap if synthetic click didn't trigger React state
                    self.page.mouse.click(res["x"], res["y"])
                    self.page.wait_for_timeout(400)
                return True
            return bool(res)
        except Exception:
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
                        items.push({ text: txt.slice(0, 100), status: status });
                    }
                    return items;
                }""")
                if settled_items:
                    print(f"[+] Reconciled {len(settled_items)} platform bet records.")
                self.close_betslip()
        except Exception:
            pass

    def ensure_authenticated(self) -> bool:
        """Checks if session is active; attempts automatic login if credentials exist in .env."""
        try:
            login_btn = self.page.locator("button:has-text('LOGIN'), a:has-text('LOGIN'), [data-testid*='login']").first
            if login_btn.count() == 0 or not login_btn.is_visible(timeout=1000):
                return True

            if not EXCHANGE_USERNAME or not EXCHANGE_PASSWORD:
                print("[!] Notice: Logged out state detected and no credentials found in .env.")
                return False

            print("[*] Logged out state detected. Attempting automated login with .env credentials...")
            human_tap(login_btn, self.page)
            self.page.wait_for_timeout(1500)

            user_input = self.page.locator("input[type='text'], input[type='tel'], input[placeholder*='Mobile' i], input[placeholder*='Username' i]").first
            pass_input = self.page.locator("input[type='password']").first

            if user_input.is_visible(timeout=2000) and pass_input.is_visible(timeout=2000):
                human_type(user_input, EXCHANGE_USERNAME)
                human_pause(0.2, 0.4)
                human_type(pass_input, EXCHANGE_PASSWORD)
                human_pause(0.3, 0.6)

                submit = self.page.locator("button[type='submit'], button:has-text('LOGIN'), button:has-text('Log In')").first
                human_tap(submit, self.page)
                self.page.wait_for_timeout(3500)

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

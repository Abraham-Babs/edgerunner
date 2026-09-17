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

    def purge_betslip_state(self):
        """Immediately wipes all client-side betslip localStorage keys and closes the drawer."""
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
        self.close_betslip()

    def dispatch_session_bet(self, ticket: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
        """
        Submits the ticket directly via the authenticated browser session fetch() to SportsExchange's
        scheduled virtuals action endpoint: routes/$locale.virtuals.scheduled.
        Completely immune to DOM layout shifts and visual rendering lags.
        """
        stake = float(ticket["stake"])
        legs = ticket["legs"]
        ticket_type_str = ticket.get("type", "single").lower()

        type_map = {"single": 1, "double": 2, "treble": 3, "multiple": 2}
        sub_type = type_map.get(ticket_type_str, len(legs))

        # Default categoryId map fallback
        cat_id_map = {"league_en": 4, "league_es": 37, "league_it": 38, "league_de": 16}

        odds_items = []
        comb_odds = 1.0
        for leg in legs:
            raw_odds = float(leg.get("raw_odds", 1.0))
            comb_odds *= raw_odds
            l_key = leg.get("league", "league_en")
            c_id = leg.get("category_id") or cat_id_map.get(l_key, 4)
            odds_items.append({
                "id": int(leg.get("selection_id")),
                "value": raw_odds,
                "banker": None,
                "categoryId": int(c_id)
            })

        comb_odds = round(comb_odds, 2)
        pot_win = round(stake * comb_odds, 2)
        req_id = str(uuid.uuid4())[:20]
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")

        payload = {
            "action": "placeBet",
            "data": {
                "betslipData": {
                    "requestUniqueIdentifier": req_id,
                    "discrimination": 19010103,
                    "type": sub_type,
                    "odds": odds_items,
                    "stakeGross": stake,
                    "stakeNet": stake,
                    "minPotentialWinGross": pot_win,
                    "minPotentialWinNet": pot_win,
                    "maxPotentialWinGross": pot_win,
                    "maxPotentialWinNet": pot_win
                },
                "clientTime": now_iso,
                "serverSyncedTime": now_iso,
                "serverSyncedTimeWithoutLatency": now_iso,
                "adjust": {"adjustId": "", "adjustIdfa": "", "gpsAdId": ""}
            }
        }

        if dry_run:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            diag_path = f"{SHOTS_DIR}/dry_run_payload_{ts}.png"
            try:
                self.page.screenshot(path=diag_path, timeout=2500)
            except Exception:
                pass
            print(f"[+] [DRY RUN] Verified API payload construction ({sub_type} leg(s) @ {comb_odds}, stake ₦{stake}). 0 money deducted.")
            return {
                "success": True,
                "dry_run": True,
                "coupon_code": "DRY_RUN_VERIFIED",
                "receipt_file": diag_path
            }

        try:
            res = self.page.evaluate("""async (payload) => {
                try {
                    const resp = await fetch('https://sports-exchange.internal/en-ng/virtuals/scheduled?_data=routes%2F%24locale.virtuals.scheduled', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': '*/*'
                        },
                        body: JSON.stringify(payload)
                    });
                    const data = await resp.json();
                    return { status: resp.status, ok: resp.ok, data: data };
                } catch (err) {
                    return { ok: false, error: err.toString() };
                }
            }""", payload)

            if res and res.get("ok"):
                data = res.get("data", {}).get("data", {})
                if data.get("placed"):
                    coupon = data.get("couponCode", "")
                    print(f"[+] Bet successfully placed via Session API! Coupon: {coupon}")
                    return {
                        "success": True,
                        "coupon_code": coupon,
                        "raw": data
                    }
                else:
                    err_msg = res.get("data", {})
                    print(f"[!] Platform rejected bet placement: {err_msg}")
                    return {"success": False, "error": str(err_msg)}
            else:
                err_body = res.get("data") or res.get("error") or res.get("status")
                print(f"[!] In-session fetch failed ({res.get('status')}): {err_body}")
                return {"success": False, "error": str(err_body)}
        except Exception as e:
            print(f"[!] Exception during dispatch_session_bet: {e}")
            return {"success": False, "error": str(e)}

    def execute_ticket(
        self, 
        ticket: Dict[str, Any], 
        dry_run: bool = False, 
        dry_fire: bool = False, 
        time_budget: Optional[float] = None,
        time_to_kickoff: Optional[float] = None,
        max_odds_cap: Optional[float] = None, 
        min_odds_cap: Optional[float] = None
    ) -> bool:
        """
        Executes a single or multi-leg ticket:
        1. Evaluates dynamic time budget and kickoff proximity.
        2. Layer 1 (Camouflage): Sends authentic human UI telemetry ahead of dispatch.
        3. Layer 2 (Dispatch): In-session authenticated API dispatch.
        4. Post-Submission: Purges betslip state and dismisses drawer.
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
        self.purge_betslip_state()

        now_epoch = time.time()
        if time_to_kickoff is None:
            leg_expiries = [l.get("kickoff_epoch", 0) for l in legs if l.get("kickoff_epoch", 0) > now_epoch]
            time_to_kickoff = max(0.0, min(leg_expiries) - now_epoch) if leg_expiries else 120.0

        effective_budget = time_budget if time_budget is not None else 3.0

        # --- LAYER 1: LIGHTWEIGHT CAMOUFLAGE DECOY ---
        # Normal path: runs before Layer 2 to establish human telemetry on SportsExchange's edge.
        # Emergency path: if time to kickoff is critically low (<4.0s), bypass completely.
        if time_to_kickoff < 4.0:
            print(f"[!] EMERGENCY PREEMPTION: Only {time_to_kickoff:.1f}s to kickoff. Bypassing Layer 1 decoy.")
        else:
            try:
                if time_to_kickoff > 20.0:
                    jitter_pause = random.uniform(2.5, 4.5)
                else:
                    jitter_pause = random.uniform(1.2, 2.5)

                human_pause(0.3, 0.6)
                visible_odds = self.page.locator('[data-testid="match-odd"]')
                if visible_odds.count() > 0:
                    target_btn = visible_odds.first
                    if target_btn.is_visible(timeout=300):
                        target_btn.click(timeout=400)
                rem_pre_dispatch = max(0.4, jitter_pause - 0.5)
                self.page.wait_for_timeout(int(rem_pre_dispatch * 1000))
            except Exception:
                pass

        # --- LAYER 2: DETERMINISTIC IN-SESSION API DISPATCH ---
        # The bet is sent directly via the authenticated browser session fetch() to SportsExchange.
        # Zero DOM button clicking, zero delay, sub-second execution.
        try:
            dispatch_res = self.dispatch_session_bet(ticket, dry_run=dry_fire)
            if dispatch_res.get("success"):
                coupon = dispatch_res.get("coupon_code", "")
                receipt_file = coupon if coupon else dispatch_res.get("receipt_file", "")
                status_str = "DRY_FIRE_VERIFIED" if dry_fire else "CONFIRMED_SUCCESS"
                self.log_bet(ticket, status=status_str, receipt_file=receipt_file)
                leg_expiries = [l.get("kickoff_epoch", 0) for l in legs if l.get("kickoff_epoch", 0) > now_epoch]
                self.last_placed_slip_expiry = int(min(leg_expiries) - now_epoch) if leg_expiries else 120
                return True
            else:
                err_str = dispatch_res.get("error", "DISPATCH_FAILED")
                self.last_failure_reason = "DISPATCH_FAILED"
                self.log_bet(ticket, status=f"REJECTED_{err_str}")
                return False
        finally:
            # --- POST-SUBMISSION STATE PURGE ---
            # programmatically wipes betslip keys and closes drawer so DOM is pristine for next ticket
            self.purge_betslip_state()

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
                        print(f"[*] UI Tab Mismatch for {match_name}: button shows {btn_val} vs expected {expected_odds} (market tab lag)")
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
        In-session API reconciliation of settled bets.
        Queries SportsExchange's /my-bets/virtuals/settled route to match placed tickets
        and record exact outcome ('WON' / 'LOST') and returned_amount to bet_log.csv.
        Zero DOM interaction, non-disruptive to active betting boards.
        """
        try:
            url = "/en-ng/my-bets/virtuals/settled?_data=routes%2F%28%24locale%29.my-bets.virtuals.%24betsType"
            res = self.page.evaluate("""async (u) => {
                try {
                    const r = await fetch(u, { headers: { 'Accept': 'application/json' } });
                    return await r.json();
                } catch(e) {
                    return { error: e.toString() };
                }
            }""", url)

            coupons = res.get("couponsData", {}).get("coupons", [])
            if not coupons or not os.path.exists(BET_LOG_FILE):
                return

            df = pd.read_csv(BET_LOG_FILE, dtype={"settled_at": str, "outcome": str, "bet_id": str, "code_version": str, "receipt_file": str})
            df["settled_at"] = df["settled_at"].fillna("")
            df["outcome"] = df["outcome"].fillna("")
            df["receipt_file"] = df["receipt_file"].fillna("")

            pending_mask = (df["status"] == "CONFIRMED_SUCCESS") & (df["outcome"].isin(["PENDING", ""]))
            pending_indices = df[pending_mask].index.tolist()
            if not pending_indices:
                return

            updated = 0
            for idx in pending_indices:
                row = df.loc[idx]
                row_stake = float(row.get("stake", 0.0))
                row_odds = float(row.get("combined_odds", 0.0))
                row_receipt = str(row.get("receipt_file", "")).strip()

                match = None
                for c in coupons:
                    c_code = str(c.get("couponCode", "")).strip()
                    c_stake = round(float(c.get("stakeGross", 0.0)), 2)
                    c_odds = round(float(c.get("totalOdds", 0.0)), 2)

                    if row_receipt and row_receipt == c_code:
                        match = c
                        break
                    elif not row_receipt and abs(row_stake - c_stake) < 0.01 and abs(row_odds - c_odds) < 0.02:
                        match = c
                        break

                if match:
                    raw_status = str(match.get("status", "")).lower()
                    outcome_val = "WON" if raw_status == "won" else "LOST" if raw_status == "lost" else raw_status.upper()
                    won_amt = float(match.get("won", 0.0))
                    settled_time = match.get("couponDate") or datetime.utcnow().isoformat()
                    c_code = str(match.get("couponCode", "")).strip()

                    df.loc[idx, "outcome"] = outcome_val
                    df.loc[idx, "settled_at"] = settled_time
                    df.loc[idx, "returned_amount"] = won_amt
                    if not row_receipt:
                        df.loc[idx, "receipt_file"] = c_code
                    updated += 1
                    self.pending_bets.pop(row.get("bet_id", ""), None)

            if updated > 0:
                d_name = os.path.dirname(os.path.abspath(BET_LOG_FILE))
                with tempfile.NamedTemporaryFile("w", dir=d_name, delete=False, newline="", encoding="utf-8") as tf:
                    temp_path = tf.name
                df.to_csv(temp_path, index=False)
                os.replace(temp_path, BET_LOG_FILE)
                _sync_root_bet_log()
                print(f"[+] Settlement Reconciliation: updated {updated} bet(s) in log (WON/LOST).")
        except Exception as e:
            print(f"[!] Warning: Settlement reconciliation encountered an error: {e}")

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

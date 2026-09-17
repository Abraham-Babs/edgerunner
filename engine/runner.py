"""
engine/runner.py
----------------
The brain of the operation. Orchestrates concurrent HTTP/2 discovery across
all four virtual football leagues, cross-references live odds against statistical
Poisson models, constructs positive-EV tickets, and executes them via Playwright.

Execution Architecture:
  1. Discovery: Unauthenticated HTTP/2 polls all 4 leagues concurrently in ~1.5s,
     syncing with server clock skew and caching positive-EV edges into MasterBoard.
  2. Model: Odds are cross-checked against Poisson lambda models — only bets
     with mathematically positive expected value (+EV) are qualified.
  3. Execution: Browser opens only when qualified tickets exist, using mobile touch
     tap events, preloader purging, and zero-tolerance in-betslip validation.
  4. Capital Protection: Pure fractional bankroll allocation (3-4% per bet,
     preserving ~85% in cash) with hard liquidation stop-loss floor. No artificial
     cooldowns or streak pauses on memoryless RNG rounds.

Runtime options:
  --profile     : 'ultra_conservative' (default), 'conservative', or 'balanced'
  --dry-run     : Simulate tickets and capture screenshot verification without betting
  --max-rounds  : Stop after N cycles. 0 = run forever.
"""

import os
import sys
import time
import random
import argparse
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from engine.config import (
    LEAGUES, USER_DATA_DIR, ITEL_USER_AGENT,
    MAX_ACTIVE_PENDING_BETS, MAX_CONSECUTIVE_FAILURES
)
from engine.edge_matcher import EdgeMatcher
from engine.ticket_builder import TicketBuilder
from engine.master_board import MasterBoard
from engine.discovery.client import PublicDiscoveryClient
from engine.bettor import Bettor
from engine.parser import clean_page
from engine.human_interaction import human_pause

class RiskManager:
    """
    Manages account capital and exposure limits during live execution.

    Key responsibilities:
    - Tracks 'True Equity' (liquid balance + pending unsettled stakes).
    - Hard stop-loss liquidation protection: terminates immediately if equity
      falls below 50% of starting capital or ₦100.
    - Manages portfolio mode and stake sizing based on active true equity.
    - Limits total concurrent in-play tickets (max 4 in ultra_conservative).
    """
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.peak_balance = initial_balance
        self.consecutive_losses = 0
        self.consecutive_failures = 0
        self.active_bets = []  # Tracks currently unsettled bets: [{timestamp, stake, league}]

    def clean_expired_bets(self):
        """
        Removes bets from the active tracking list once their scheduled round
        and match play duration has elapsed.
        """
        now = time.time()
        self.active_bets = [b for b in self.active_bets if now < b.get("expiry_timestamp", b["timestamp"] + 180)]

    def add_active_bet(self, stake: float, league: str = "", match_keys: List[str] = None, duration_sec: Optional[float] = None):
        ttl = (duration_sec + 95) if (duration_sec and duration_sec > 0) else 240
        self.active_bets.append({
            "timestamp": time.time(),
            "expiry_timestamp": time.time() + ttl,
            "stake": stake,
            "league": league,
            "match_keys": match_keys or []
        })

    def has_active_match(self, match_key: str) -> bool:
        self.clean_expired_bets()
        for b in self.active_bets:
            if match_key in b.get("match_keys", []):
                return True
        return False

    def get_pending_stake(self) -> float:
        self.clean_expired_bets()
        return sum(b["stake"] for b in self.active_bets)

    def can_place_bet(self) -> bool:
        self.clean_expired_bets()
        return len(self.active_bets) < MAX_ACTIVE_PENDING_BETS

    def get_portfolio_mode(self, current_balance: float) -> dict:
        self.clean_expired_bets()
        pending_stake = self.get_pending_stake()
        true_equity = current_balance + pending_stake

        # Institutional thresholds purely governed by available bankroll / true equity
        if true_equity < 1200.0:
            return {
                "name": "BEDROCK_SHIELD",
                "profile": "ultra_conservative",
                "allow_conservative": False,
                "allow_doubles": True,
                "max_double_odds": 2.80,
                "allow_treble": False,
                "allow_satellite": False,
                "satellite_pct": 0.0,
                "max_tickets": 2,
                "min_odds": 1.45,
                "max_odds": 3.50,
                "true_equity": true_equity,
            }
        elif true_equity < 6000.0:
            return {
                "name": "CORE_GROWTH",
                "profile": "ultra_conservative",
                "allow_conservative": False,
                "allow_doubles": True,
                "max_double_odds": 3.00,
                "allow_treble": False,
                "allow_satellite": False,
                "satellite_pct": 0.0,
                "max_tickets": 2,
                "min_odds": 1.45,
                "max_odds": 3.50,
                "true_equity": true_equity,
            }
        else:
            return {
                "name": "EXPANSION_RATCHET",
                "profile": "ultra_conservative",
                "allow_conservative": True,
                "allow_doubles": True,
                "max_double_odds": 3.50,
                "allow_treble": True,
                "allow_satellite": True,
                "satellite_pct": 0.05,
                "max_tickets": 3,
                "max_odds": 6.00,
                "true_equity": true_equity,
            }

    def update_balance(self, page, current_balance: float):
        self.clean_expired_bets()
        pending_stake = self.get_pending_stake()
        
        # True Equity = Cash + In-play Stakes
        true_equity = current_balance + pending_stake

        # Hard Stop-Loss Floor (< ₦100 or 50% deposit loss)
        if true_equity < 100.0 or true_equity <= (self.initial_balance * 0.50):
            print("\n" + "!"*60)
            print(f"[!] HARD STOP-LOSS: Capital floor breached. Equity=₦{true_equity:,.2f} (Initial: ₦{self.initial_balance:,.2f})")
            print("    Terminating engine immediately to protect remaining bankroll.")
            print("!"*60 + "\a\a\n")
            return "STOP_LOSS"

        return "OK"

    def record_bet_result(self, won: bool):
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

    def record_submission_attempt(self, success: bool) -> str:
        if success:
            self.consecutive_failures = 0
            return "OK"
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= (MAX_CONSECUTIVE_FAILURES * 2):
                print("\n" + "!"*60)
                print(f"[!] HARD EXIT: {self.consecutive_failures} consecutive bet submissions failed!")
                print("    Platform layout may have changed. Diagnostic screenshots saved to SHOTS_DIR.")
                print("    Terminating engine to prevent wasted attempts.")
                print("!"*60 + "\a\a\a\n")
                sys.exit(1)
            elif self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"[!] Warning: {self.consecutive_failures} consecutive failed submissions. Triggering self-healing recovery...")
                return "SELF_HEAL"
            return "FAIL"

_wallet_api_url = "/api/account/v1/users/me/wallet"
_last_known_balance = 0.0

def attach_wallet_listener(page):
    """
    Passively monitors network traffic to auto-detect any shifts in the platform's
    wallet/balance endpoint and keep the server balance updated in real-time.
    """
    def _on_response(response):
        global _wallet_api_url, _last_known_balance
        url = response.url
        if any(term in url.lower() for term in ["/wallet", "users/me/wallet", "/balance"]):
            try:
                if "sports-exchange.internal" in url:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    new_path = parsed.path + (("?" + parsed.query) if parsed.query else "")
                    if new_path and new_path != _wallet_api_url:
                        _wallet_api_url = new_path
                data = response.json()
                bal = None
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], dict) and "balance" in data["data"]:
                        bal = float(data["data"]["balance"])
                    elif "balance" in data:
                        bal = float(data["balance"])
                if bal is not None and bal > 0:
                    _last_known_balance = bal
            except Exception:
                pass
    page.on("response", _on_response)

def get_live_balance(page, retries: int = 3) -> float:
    """
    Pure server truth: queries the platform server wallet API directly via in-browser
    fetch replay using active cookies and session headers. No DOM parsing.
    """
    global _wallet_api_url, _last_known_balance
    for attempt in range(1, retries + 1):
        try:
            res = page.evaluate(f"""async (url) => {{
                try {{
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 4000);
                    const resp = await fetch(url, {{
                        method: 'GET',
                        headers: {{ 'Accept': 'application/json, text/plain, */*' }},
                        signal: controller.signal
                    }});
                    clearTimeout(timeoutId);
                    if (!resp.ok) return {{ ok: false, status: resp.status }};
                    const data = await resp.json();
                    return {{ ok: true, data: data }};
                }} catch(e) {{
                    return {{ ok: false, error: e.toString() }};
                }}
            }}""", _wallet_api_url)

            if res and res.get("ok"):
                data = res.get("data", {})
                bal = None
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], dict) and "balance" in data["data"]:
                        bal = float(data["data"]["balance"])
                    elif "balance" in data:
                        bal = float(data["balance"])
                if bal is not None and bal > 0:
                    _last_known_balance = bal
                    return _last_known_balance
        except Exception:
            pass
        page.wait_for_timeout(400)
    return _last_known_balance

def safe_navigate_or_reload(page, url: str, bettor: Bettor = None, max_retries: int = 3, timeout_ms: int = 35000) -> bool:
    """
    Resilient navigation designed for high-latency / jittery networks.
    Ensures the page has actually landed on sports-exchange.internal and hydrated required interactive elements.
    """
    for attempt in range(1, max_retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if page.url and not page.url.startswith("about:") and "sports-exchange.internal" in page.url:
                try:
                    page.locator('[data-testid="match-odd"], button:has-text("Week ")').first.wait_for(state="visible", timeout=20000)
                except Exception:
                    pass
                clean_page(page)
                return True
        except Exception as e:
            print(f"[!] Network error (attempt {attempt}/{max_retries}) navigating to {url}: {e}")
            if attempt < max_retries:
                backoff = attempt * 3
                print(f"[*] Re-navigating in {backoff}s...")
                time.sleep(backoff)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if page.url and not page.url.startswith("about:") and "sports-exchange.internal" in page.url:
                        clean_page(page)
                        return True
                except Exception as re_err:
                    print(f"[!] Re-navigation attempt failed: {re_err}")
    if bettor:
        bettor.capture_diagnostic("network_failure")
    return False


def execute_master_board_bets(page, matcher: EdgeMatcher, builder: TicketBuilder, bettor: Bettor, risk: RiskManager, master_board: MasterBoard, portfolio_mode: dict, balance: float, dry_run: bool = False):
    """
    Builds and executes tickets using the unified cross-league, cross-week candidate pool.
    """
    max_active_cap = matcher.profile.get("max_concurrent_bets", MAX_ACTIVE_PENDING_BETS)
    if len(risk.active_bets) >= max_active_cap:
        print(f"[*] Active capacity limit reached ({len(risk.active_bets)}/{max_active_cap} bets in play). Waiting for settlements.")
        return

    all_candidates = master_board.get_all_candidates()
    # Filter out active matches to prevent duplicate exposure on the same match
    valid_candidates = [
        c for c in all_candidates 
        if not risk.has_active_match(f"{c.get('league', '')} | {c.get('match_name', '')}")
    ]

    print(f"[*] Master Board Pool: {len(valid_candidates)} eligible positive-EV edges across all 4 leagues.")

    if not valid_candidates:
        print("[-] No valid positive-EV selections met criteria across any league this cycle.")
        return

    # Build cross-league, cross-week tickets
    tickets = builder.build_tickets(
        valid_candidates,
        balance=balance,
        max_tickets=portfolio_mode.get("max_tickets", 3),
        profile=matcher.profile,
        portfolio_mode=portfolio_mode
    )

    # 1. Tag and Sort Tickets by Earliest Kickoff (EDF: Earliest Deadline First)
    now_ts = time.time()
    def get_ticket_earliest_ko(t):
        kos = [l.get("kickoff_epoch", 0) for l in t.get("legs", []) if l.get("kickoff_epoch", 0) > now_ts]
        return min(kos) if kos else (now_ts + 180.0)

    for t in tickets:
        t["_earliest_ko"] = get_ticket_earliest_ko(t)

    tickets.sort(key=lambda t: t["_earliest_ko"])

    print(f"[+] Master Builder assembled {len(tickets)} optimal ticket(s) (EDF sorted):")
    for idx, t in enumerate(tickets, 1):
        leg_summary = " + ".join([f"{l.get('league', '').upper()} {l.get('week', '')} {l.get('match_name')}" for l in t["legs"]])
        time_to_ko = max(0.0, t["_earliest_ko"] - now_ts)
        print(f"    Ticket {idx} [{t['type'].upper()} | {t['role']}]: {leg_summary} @ {t['combined_odds']} (Stake: ₦{t['stake']} | T-{time_to_ko:.0f}s)")

    safety_margin = 5.0

    for idx, ticket in enumerate(tickets, 1):
        if len(risk.active_bets) >= max_active_cap:
            rem_cnt = len(tickets) - idx + 1
            print(f"[*] Active risk capacity full ({max_active_cap}/{max_active_cap}). Preserving {rem_cnt} ticket(s) on MasterBoard for next cycle.")
            break

        curr_now = time.time()
        ticket_ko = ticket.get("_earliest_ko", curr_now + 120.0)
        time_to_ko = max(0.0, ticket_ko - curr_now)

        # Equal-Slack: look ahead at all remaining tickets to calculate bottleneck time slice
        remaining_tickets = tickets[idx - 1:]
        step_slacks = []
        for k_idx, fut_t in enumerate(remaining_tickets):
            fut_ko = fut_t.get("_earliest_ko", curr_now + 120.0)
            avail_k = max(0.0, fut_ko - curr_now - safety_margin)
            step_slacks.append(avail_k / (k_idx + 1))

        bottleneck_slack = min(step_slacks) if step_slacks else 15.0
        t_budget = max(1.5, min(20.0, bottleneck_slack))

        t_type = ticket.get("type", "single")
        if t_type == "double":
            t_max_odds = portfolio_mode.get("max_double_odds", 2.80)
        elif t_type == "treble":
            t_max_odds = 4.20
        else:
            t_max_odds = portfolio_mode.get("max_odds", 2.10)

        success = bettor.execute_ticket(
            ticket, 
            dry_run=dry_run, 
            time_budget=t_budget,
            time_to_kickoff=time_to_ko,
            max_odds_cap=t_max_odds,
            min_odds_cap=portfolio_mode.get("min_odds", 1.45)
        )
        if success:
            risk.record_submission_attempt(True)
            if not dry_run:
                m_keys = [f"{l.get('league', '')} | {l.get('match_name', '')}" for l in ticket["legs"]]
                risk.add_active_bet(
                    ticket["stake"],
                    league=ticket["legs"][0].get("league", ""),
                    match_keys=m_keys,
                    duration_sec=bettor.last_placed_slip_expiry
                )
        else:
            # If aborted due to round expiry, expired banner, button missing, odds mismatch, or league switch timeout, do not penalize failure budget
            reason = getattr(bettor, "last_failure_reason", None)
            if reason in ("EXPIRED_TIMER", "EXPIRED_BANNER", "BUTTON_NOT_FOUND", "LEAGUE_SWITCH_FAILED", "ODDS_MISMATCH", "MATCH_MISMATCH", "EXCEEDS_MAX_ODDS", "BELOW_MIN_ODDS"):
                print(f"[*] Ticket aborted ({reason}). Moving on to next edge candidate.")
                # Immediately evict this round from master board so it is never picked again
                for leg in ticket.get("legs", []):
                    lg = leg.get("league", "")
                    wk = leg.get("week", "")
                    if lg and wk:
                        master_board.evict_week(lg, wk)
                continue

            # If network disconnected or platform error overlay present, recover without penalizing submission attempt budget
            is_offline = False
            try:
                is_offline = not page.evaluate("""() => {
                    if (!navigator.onLine) return false;
                    const txt = document.body ? document.body.innerText : '';
                    if (txt.includes('encountered an issue loading data') || txt.includes('REFRESH PAGE')) return false;
                    return true;
                }""")
            except Exception:
                is_offline = True

            if is_offline:
                print("[!] Platform reload overlay or network drop detected. Waiting 15s for recovery...")
                try:
                    ref = page.locator("button:has-text('REFRESH PAGE')").first
                    if ref.count() > 0 and ref.is_visible():
                        ref.click()
                except Exception:
                    pass
                time.sleep(15)
                continue

            sub_status = risk.record_submission_attempt(False)
            if sub_status == "SELF_HEAL":
                print("[*] Self-healing: purging stale master board, clearing betslip, and reloading page...")
                master_board.clear()
                bettor.clear_betslip_selections()
                bettor.close_betslip()
                page.reload(wait_until="commit", timeout=12000)
                page.wait_for_timeout(2000)
                clean_page(page)
                break

        # Equal-Slack Adaptive Inter-Ticket Pacing:
        if idx < len(tickets):
            post_now = time.time()
            remaining_after = tickets[idx:]
            after_slacks = []
            for k_idx, fut_t in enumerate(remaining_after):
                fut_ko = fut_t.get("_earliest_ko", post_now + 120.0)
                avail_k = max(0.0, fut_ko - post_now - safety_margin)
                after_slacks.append(avail_k / (k_idx + 1))

            future_slack = min(after_slacks) if after_slacks else 15.0

            # Natural human distribution:
            # 1. Occasional fast-follow surge (12% probability): 5s-7.5s gap if slack allows
            roll_surge = random.random()
            if roll_surge < 0.12 and future_slack >= 6.0:
                inter_delay = random.uniform(5.0, 7.5)
            # 2. Generous slack: smooth human 14s-26s spacing
            elif future_slack >= 24.0:
                inter_delay = random.uniform(14.0, min(26.0, future_slack * 0.75))
            # 3. Moderate slack: 9s-14s spacing
            elif future_slack >= 11.0:
                inter_delay = random.uniform(9.0, min(14.0, future_slack * 0.85))
            # 4. Compressed slack: 5s-8s spacing
            else:
                inter_delay = max(5.0, min(8.0, future_slack * 0.9))

            actual_delay = max(5.0, min(inter_delay, future_slack)) if future_slack > 5.0 else max(1.0, future_slack)
            print(f"[*] Adaptive Pacing: spacing next ticket by {actual_delay:.1f}s (global slack: {future_slack:.1f}s)...")
            human_pause(actual_delay * 0.85, actual_delay)

def run_loop(profile: str = "ultra_conservative", dry_run: bool = False, max_rounds: int = 0):
    print("==================================================")
    print(f"[*] STARTING EXCHANGE VALUE BETTING ENGINE (MASTER BOARD)")
    print(f"[*] Profile: {profile.upper()} | Dry Run: {dry_run}")
    print(f"[*] Architecture: Unified Rolling Master Board (Cross-League & Cross-Week)")
    print("==================================================")

    matcher = EdgeMatcher(profile_name=profile)
    builder = TicketBuilder()
    master_board = MasterBoard()
    discovery_client = PublicDiscoveryClient(timeout=25.0)
    league_keys = list(LEAGUES.keys())

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=True,
            viewport={"width": 360, "height": 806},
            device_scale_factor=2.0,
            is_mobile=True,
            has_touch=True,
            user_agent=ITEL_USER_AGENT,
            locale="en-NG",
            timezone_id="Africa/Lagos",
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        # Permanently block promotional popups, game modals, iframes, and trackers at network level
        page.route("**/*free2play*", lambda r: r.abort())
        page.route("**/*premier-game*", lambda r: r.abort())
        page.route("**/*exchange-core-account.workers.dev*", lambda r: r.abort())
        page.route("**/*google*analytics*", lambda r: r.abort())
        page.route("**/*doubleclick*", lambda r: r.abort())
        page.route("**/*facebook*", lambda r: r.abort())
        page.route("**/*bing*", lambda r: r.abort())
        page.route("**/*t.co*", lambda r: r.abort())
        page.route("**/*px.oa.opera.com*", lambda r: r.abort())
        bettor = Bettor(page)
        attach_wallet_listener(page)

        # Navigate to first league to authenticate and load real balance
        first_league = LEAGUES[league_keys[0]]
        safe_navigate_or_reload(page, first_league["url"], bettor=bettor)
        if not bettor.ensure_authenticated():
            print("[!] HARD EXIT: Initial login verification failed. Check credentials in .env.")
            sys.exit(1)

        print("[*] Contacting SportsExchange wallet server for verified bankroll...")
        init_balance = 0.0
        for b_attempt in range(10):
            init_balance = get_live_balance(page)
            if init_balance > 0.0:
                break
            page.wait_for_timeout(800)

        if init_balance <= 0.0:
            print("[!] HARD EXIT: Server wallet returned 0.0 or unreadable. Halting to protect capital.")
            sys.exit(1)

        risk = RiskManager(initial_balance=init_balance)
        print(f"[+] Initialized Risk Manager with Verified Starting Bankroll: ₦{init_balance:,.2f}")
        bettor.reconcile_settled_bets()

        rounds_completed = 0
        try:
            while True:
                rounds_completed += 1
                print(f"\n==================================================")
                print(f"[*] STARTING MASTER ROUND CYCLE #{rounds_completed}")
                print(f"==================================================")

                matcher.check_and_reload()

                # 1. Update live balance and portfolio mode
                balance = get_live_balance(page)
                status = risk.update_balance(page, balance)
                if status == "STOP_LOSS":
                    sys.exit(0)

                portfolio_mode = risk.get_portfolio_mode(balance)
                net_pnl = balance - risk.initial_balance
                pnl_pct = (net_pnl / risk.initial_balance) * 100 if risk.initial_balance > 0 else 0.0
                pending_stake = risk.get_pending_stake()
                active_cnt = len(risk.active_bets)
                pnl_sign = "+" if net_pnl >= 0 else "-"

                print(f"┌──────────────────────────────────────────────────────────────────┐")
                print(f"│  SESSION SCORECARD (Round #{rounds_completed}){' ' * max(0, 39 - len(str(rounds_completed)))}│")
                print(f"├──────────────────────────────────────────────────────────────────┤")
                print(f"│  Starting Bankroll : ₦{risk.initial_balance:>10,.2f}{' ' * 33}│")
                print(f"│  Current Balance   : ₦{balance:>10,.2f}{' ' * 33}│")
                print(f"│  Net Profit / Loss : {pnl_sign}₦{abs(net_pnl):>9,.2f} ({pnl_pct:>+6.2f}%){' ' * 23}│")
                print(f"│  Active In-Play    : ₦{pending_stake:>10,.2f} ({active_cnt} ticket{'s' if active_cnt != 1 else ' '}){' ' * 22}│")
                print(f"│  True Equity       : ₦{portfolio_mode['true_equity']:>10,.2f} | Mode: {portfolio_mode['name']:<18}│")
                print(f"└──────────────────────────────────────────────────────────────────┘")

                # 2. Phase 1: Fast HTTP discovery sync across all 4 leagues (no browser navigation)
                try:
                    disc_payload = discovery_client.discover_all_leagues(
                        matcher,
                        profile_name=portfolio_mode["profile"],
                        allow_conservative=portfolio_mode["allow_conservative"]
                    )
                    master_board.sync_from_discovery(disc_payload)
                    total_cand = master_board.total_count()
                    proto = disc_payload.get("active_protocol", "HTTP")
                    print(f"[+] Master Board synced via {proto}: {total_cand} active positive-EV edge(s) cached.")
                except Exception as e:
                    print(f"\n[!] ALERT: Exception during HTTP discovery sync: {e}")

                # 3. Phase 2: Master cross-league ticket execution (Browser touches DOM only when tickets exist)
                try:
                    execute_master_board_bets(page, matcher, builder, bettor, risk, master_board, portfolio_mode, balance, dry_run=dry_run)
                except Exception as e:
                    print(f"\n[!] ALERT: Exception during master ticket execution: {e}")
                    bettor.capture_diagnostic("master_execution_crash")

                # 4. Settlement reconciliation and resting
                bettor.reconcile_settled_bets()

                if max_rounds > 0 and rounds_completed >= max_rounds:
                    print(f"[+] Reached target max rounds ({max_rounds}). Stopping runner.")
                    break

                rest_sec = random.randint(2, 4) if master_board.total_count() > 0 else random.randint(4, 6)
                print(f"[*] Cycle #{rounds_completed} complete. Rolling check in {rest_sec}s...")
                time.sleep(rest_sec)

        except KeyboardInterrupt:
            print("\n[*] Engine gracefully stopped by user.")
        finally:
            discovery_client.close()
            context.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SportsExchange Autonomous Betting Engine")
    parser.add_argument("--profile", default="ultra_conservative", choices=["ultra_conservative", "conservative", "balanced", "expansive"], help="Statistical edge profile")
    parser.add_argument("--dry-run", action="store_true", help="Simulate bet construction without placing real bets")
    parser.add_argument("--max-rounds", type=int, default=0, help="Stop after N full 4-league cycles (0 for continuous)")
    args = parser.parse_args()

    run_loop(profile=args.profile, dry_run=args.dry_run, max_rounds=args.max_rounds)

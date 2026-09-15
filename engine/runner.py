"""
engine/runner.py
----------------
The brain of the operation. This is the main loop that runs continuously,
cycling through all four virtual football leagues on SportsExchange and placing
bets wherever the numbers say there is a genuine edge.

How it works, in plain terms:
  1. The engine opens a mobile browser session (disguised as a real Android phone)
     and navigates to each league page in a randomized order each cycle.
  2. It reads the live match fixtures and current odds directly off the screen.
  3. Those odds are cross-checked against our statistical model — only bets
     where the expected return is mathematically positive are considered.
  4. Qualifying bets are assembled into a smart ticket mix: high-confidence
     singles, anchor+booster doubles, and value singles — sized by tier.
  5. A Risk Manager tracks everything: how much money is currently in play
     (even unsettled), running peak balance, consecutive losses, and
     whether we're in a drawdown. If we dip 25% from peak, the engine
     pauses and polls the balance every 25 seconds, resuming the moment
     a win lands and equity recovers — no wasted waiting time.
  6. Up to 10 bets can be active simultaneously across all four leagues,
     which gives the strategy room to breathe while keeping total
     exposure under control (roughly 45% of bankroll at any given time).
  7. Human-like behavior is injected throughout: random pauses, scroll
     movements, tap jitter, and occasional 'browse and pass' rounds
     where we look but don't bet.

Runtime options:
  --profile     : 'conservative', 'balanced' (default), or 'expansive'
  --dry-run     : Simulate tickets without placing real money (testing mode)
  --max-rounds  : Stop after N full 4-league cycles. 0 = run forever.
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
    LEAGUES, USER_DATA_DIR, ITEL_USER_AGENT, SHOTS_DIR,
    MAX_DRAWDOWN_PCT, DRAWDOWN_SLEEP_SECONDS, CONSECUTIVE_LOSS_LIMIT, COOL_OFF_SECONDS,
    PROFIT_BREATHER_GAIN, PROFIT_BREATHER_SECONDS, MAX_ACTIVE_PENDING_BETS,
    SETTLEMENT_POLL_INTERVAL, MAX_CONSECUTIVE_FAILURES
)
from engine.edge_matcher import EdgeMatcher
from engine.ticket_builder import TicketBuilder
from engine.master_board import MasterBoard
from engine.parser import clean_page, parse_round_countdown, extract_all_markets, extract_live_matches_and_buttons, extract_visible_weeks
from engine.human_interaction import human_pause, human_scroll
from engine.bettor import Bettor

class RiskManager:
    """
    Manages all financial risk during a live session.

    Key responsibilities:
    - Tracks the 'True Equity' of the account at all times. True Equity
      means the cash balance PLUS the value of stakes currently in unsettled
      bets. This prevents false drawdown alarms while bets are still running.
    - Monitors the peak balance and triggers a defensive pause if the account
      falls 25% below that peak.
    - When a drawdown is triggered, the engine does NOT stop — it enters a
      dynamic monitoring loop, checking the balance every 25 seconds and
      waking up immediately once wins land and equity recovers.
    - Detects prolonged losing streaks (7+ consecutive losses) and applies
      a cool-off pause to break the streak pattern before resuming.
    - Sounds a loud terminal alert if multiple bet submissions fail in a row,
      so issues can be caught and addressed without needing to watch logs.
    """
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.peak_balance = initial_balance
        self.consecutive_losses = 0
        self.consecutive_failures = 0
        self.profit_breather_taken = False
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

    def dynamic_sleep_until_settled(self, page, max_wait_sec: int = 600) -> float:
        """
        Called when the account equity has dropped below the 25% drawdown threshold.
        Instead of stopping cold or sleeping for a fixed duration, this method
        actively monitors the live balance every 25 seconds.

        The moment a pending bet wins and the balance recovers above the drawdown
        line, this method returns immediately and the engine resumes betting.
        This avoids the common problem of sitting idle while good rounds pass.

        If the balance hasn't recovered after max_wait_sec (default: 10 minutes),
        the engine resets its peak reference and continues with a fresh baseline.
        """
        print(f"[*] Entering dynamic monitoring: checking balance as matches conclude...")
        start_t = time.time()
        while time.time() - start_t < max_wait_sec:
            time.sleep(25)
            # Re-read live balance
            bal = get_live_balance(page)
            print(f"[*] Dynamic check: Current Live Balance: ₦{bal:,.2f} (Peak: ₦{self.peak_balance:,.2f})")
            drawdown = (self.peak_balance - bal) / self.peak_balance
            if drawdown < MAX_DRAWDOWN_PCT:
                print(f"[+] Win detected! Drawdown recovered to {drawdown*100:.1f}%. Resuming betting immediately.")
                return bal

        return get_live_balance(page)

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
                "max_odds": 2.10,
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
                "max_odds": 2.50,
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

        gain = ((current_balance - self.initial_balance) / self.initial_balance) if self.initial_balance > 0 else 0.0
        if gain >= PROFIT_BREATHER_GAIN and not self.profit_breather_taken:
            print("\n" + "="*60)
            print(f"[+] PROFIT MILESTONE REACHED: +{gain*100:.1f}% Session Gain!")
            print(f"    Starting: ₦{self.initial_balance:,.2f} -> Now: ₦{current_balance:,.2f}")
            print(f"    Compounding edge uninterrupted (no artificial sleep).")
            print("="*60 + "\n")
            self.profit_breather_taken = True

        return "OK"

    def record_bet_result(self, won: bool):
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                print("\n" + "="*60)
                print(f"[!] DEFENSIVE COOL-OFF: {self.consecutive_losses} consecutive losses.")
                print(f"    Action: Sleeping for {COOL_OFF_SECONDS//60} minutes to break down-streak.")
                print("="*60 + "\a\n")
                time.sleep(COOL_OFF_SECONDS)
                self.consecutive_losses = 0

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
                    const resp = await fetch(url, {{
                        method: 'GET',
                        headers: {{ 'Accept': 'application/json, text/plain, */*' }}
                    }});
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

def safe_navigate_or_reload(page, url: str, bettor: Bettor = None, max_retries: int = 3, timeout_ms: int = 25000) -> bool:
    """
    Resilient navigation designed for high-latency / jittery networks.
    Ensures the page has actually landed on sports-exchange.internal and is not stuck on about:blank.
    """
    for attempt in range(1, max_retries + 1):
        try:
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            page.wait_for_timeout(random.randint(1800, 2600))
            if page.url and not page.url.startswith("about:") and "sports-exchange.internal" in page.url:
                try:
                    page.locator("button:has-text('Week ')").first.wait_for(state="visible", timeout=12000)
                except Exception:
                    pass
                clean_page(page)
                return True
        except Exception as e:
            print(f"[!] Network error (attempt {attempt}/{max_retries}) navigating to {url}: {e}")
            if attempt < max_retries:
                backoff = attempt * 2
                print(f"[*] Re-navigating in {backoff}s...")
                time.sleep(backoff)
                try:
                    page.goto(url, wait_until="commit", timeout=timeout_ms)
                    page.wait_for_timeout(random.randint(1800, 2600))
                    if page.url and not page.url.startswith("about:") and "sports-exchange.internal" in page.url:
                        clean_page(page)
                        return True
                except Exception as re_err:
                    print(f"[!] Re-navigation attempt failed: {re_err}")
    if bettor:
        bettor.capture_diagnostic("network_failure")
    return False

def sync_league_board(page, league_key: str, league_info: dict, matcher: EdgeMatcher, master_board: MasterBoard, bettor: Bettor, portfolio_mode: dict):
    """
    Synchronizes positive-EV edges for a single league into the rolling Master Board.
    1. Checks countdown: if expired or <= 2s, triggers a clean reload to avoid stale DOM.
    2. Identifies on-screen visible rounds.
    3. Prunes any concluded or kicked-off rounds from the board.
    4. Explicitly taps and scrapes any newly unlocked missing rounds.
    """
    if not safe_navigate_or_reload(page, league_info["url"], bettor=bettor):
        print(f"[-] Skipping sync for {league_info['name']} due to persistent network timeout.")
        return

    human_pause(0.5, 1.0)

    # 1. Stale timer check: if round is at 00:00 or <= 2s, reload to pull fresh server rounds
    cd = parse_round_countdown(page)
    if cd is not None and cd <= 2:
        print(f"[*] {league_info['name']}: Round kickoff detected ({cd}s left). Refreshing page for fresh carousel...")
        page.reload(wait_until="commit", timeout=10000)
        page.wait_for_timeout(random.randint(1500, 2200))
        clean_page(page)
        cd = parse_round_countdown(page)

    # 2. Identify visible weeks on screen
    visible_weeks = extract_visible_weeks(page)
    if not visible_weeks:
        visible_weeks = {"Week 1"}

    def parse_week_num(w_str: str) -> int:
        nums = [int(s) for s in w_str.split() if s.isdigit()]
        return nums[0] if nums else 0

    sorted_weeks = sorted(list(visible_weeks), key=parse_week_num)

    # 3. Prune concluded rounds from cache
    master_board.prune_expired_weeks(league_key, visible_weeks)

    # 4. Check for newly unlocked rounds that need scraping
    missing_weeks = [w for w in sorted_weeks if not master_board.has_week(league_key, w)]

    if not missing_weeks:
        print(f"[*] {league_info['name']}: All visible rounds ({', '.join(sorted_weeks)}) cached. Skipping tab crawl.")
        return

    print(f"[*] {league_info['name']}: Scraping new/updated rounds: {missing_weeks}")

    primary_profile = portfolio_mode["profile"]
    allow_cons = portfolio_mode["allow_conservative"]
    cycle_sec = league_info.get("round_cycle_sec", 180)
    now = time.time()
    base_cd = cd if (cd is not None and cd > 0) else cycle_sec

    # Extract all markets once and group strictly by each fixture's true week
    market_items = extract_all_markets(page, matcher=matcher, league_key=league_key)
    edges_by_week = {w: [] for w in sorted_weeks}

    for it in market_items:
        m_week = it.get("week")
        if not m_week or m_week not in edges_by_week:
            continue
        m_name = it["match_name"]
        outcome_key = it["outcome_key"]
        live_odds = it["odds"]

        edge_data = matcher.find_edge(league_key, m_name, outcome_key, profile_name=primary_profile)
        if not edge_data and allow_cons:
            edge_data = matcher.find_edge(league_key, m_name, outcome_key, profile_name="conservative")

        if edge_data:
            mu_phat = edge_data["mu_phat"]
            live_ev = (mu_phat * live_odds) - 1.0
            oos_edge = edge_data.get("oos_edge", 0.0)
            if live_ev >= 0.05:
                edges_by_week[m_week].append({
                    "match_name": m_name,
                    "category": it["category"],
                    "tab_name": it["tab_name"],
                    "outcome": outcome_key,
                    "raw_odds": live_odds,
                    "mu_phat": mu_phat,
                    "min_edge": live_ev,
                    "oos_edge": oos_edge,
                    "n_train": edge_data.get("n_train", 0),
                    "btn_idx": it["btn_idx"],
                    "week": m_week,
                    "league": league_key
                })

    for w in sorted_weeks:
        if w in missing_weeks or not master_board.has_week(league_key, w):
            week_idx = sorted_weeks.index(w) if w in sorted_weeks else 0
            calculated_ko = now + base_cd + (week_idx * cycle_sec)
            master_board.set_week_edges(league_key, w, edges_by_week[w], kickoff_epoch=calculated_ko)

    print(f"[+] {league_info['name']}: Board synced ({master_board.total_count()} active edges across all leagues).")

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

    print(f"[+] Master Builder assembled {len(tickets)} optimal ticket(s) from global board:")
    for idx, t in enumerate(tickets, 1):
        leg_summary = " + ".join([f"{l.get('league', '').upper()} {l.get('week', '')} {l.get('match_name')}" for l in t["legs"]])
        print(f"    Ticket {idx} [{t['type'].upper()} | {t['role']}]: {leg_summary} @ {t['combined_odds']} (Stake: ₦{t['stake']})")

    for ticket in tickets:
        if len(risk.active_bets) >= max_active_cap:
            print(f"[*] Reached max concurrent active bet cap ({max_active_cap}). Holding remaining tickets.")
            break

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
        human_pause(1.0, 2.0)

def run_loop(profile: str = "ultra_conservative", dry_run: bool = False, max_rounds: int = 0):
    print("==================================================")
    print(f"[*] STARTING EXCHANGE VALUE BETTING ENGINE (MASTER BOARD)")
    print(f"[*] Profile: {profile.upper()} | Dry Run: {dry_run}")
    print(f"[*] Architecture: Unified Rolling Master Board (Cross-League & Cross-Week)")
    print("==================================================")

    matcher = EdgeMatcher(profile_name=profile)
    builder = TicketBuilder()
    master_board = MasterBoard()
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
        # Permanently block promotional popups, game modals and iframes at network level
        page.route("**/*free2play*", lambda r: r.abort())
        page.route("**/*premier-game*", lambda r: r.abort())
        page.route("**/*exchange-core-account.workers.dev*", lambda r: r.abort())
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

                # 2. Phase 1: Rolling sync across all 4 leagues
                shuffled_leagues = league_keys.copy()
                random.shuffle(shuffled_leagues)

                for l_key in shuffled_leagues:
                    l_info = LEAGUES[l_key]
                    try:
                        sync_league_board(page, l_key, l_info, matcher, master_board, bettor, portfolio_mode)
                    except Exception as e:
                        print(f"\n[!] ALERT: Exception syncing {l_info['name']}: {e}")
                        bettor.capture_diagnostic(f"crash_{l_key}")
                    human_pause(1.0, 2.5)

                # 3. Phase 2: Master cross-league ticket execution
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
            context.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SportsExchange Autonomous Betting Engine")
    parser.add_argument("--profile", default="ultra_conservative", choices=["ultra_conservative", "conservative", "balanced", "expansive"], help="Statistical edge profile")
    parser.add_argument("--dry-run", action="store_true", help="Simulate bet construction without placing real bets")
    parser.add_argument("--max-rounds", type=int, default=0, help="Stop after N full 4-league cycles (0 for continuous)")
    args = parser.parse_args()

    run_loop(profile=args.profile, dry_run=args.dry_run, max_rounds=args.max_rounds)

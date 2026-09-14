"""
test_dry_fire_suite.py
----------------------
End-to-End Dry-Fire Integration Test Suite.
Exercises 100% of the live DOM pipeline (clicking odds, multi-week targeting,
cross-league switching, betslip opening, odds & timer verification, and stake typing)
WITHOUT pressing 'PLACE BET' — protecting bankroll while visually proving system readiness.
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from engine.config import USER_DATA_DIR, ITEL_USER_AGENT, LEAGUES
from engine.bettor import Bettor
from engine.parser import clean_page, extract_all_markets

def run_dry_fire_suite():
    print("==================================================")
    print("[*] STARTING EXCHANGE DRY-FIRE TEST SUITE")
    print("[*] ZERO REAL MONEY AT RISK (Submissions Intercepted)")
    print("==================================================")

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
        bettor = Bettor(page)

        # -------------------------------------------------------------
        # TEST 1: Niche Market Single Bet (Popular / GG/NG or Over/Under)
        # -------------------------------------------------------------
        print("\n>>> TEST 1: Niche Market Single Execution (Over/Under in Premier League)")
        page.goto(LEAGUES["league_en"]["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        clean_page(page)

        # Scrape available odds to get a real fixture
        print("[*] Scanning markets...")
        markets = extract_all_markets(page)
        ou_items = [m for m in markets if m.get("tab_name") in ["O/U 2.5", "GG/NG", "Double Chance"]]
        
        if ou_items:
            target = ou_items[0]
            print(f"[+] Selected Target: {target['match_name']} | {target['tab_name']} -> Odds: {target['odds']}")
            single_ticket = {
                "type": "single",
                "stake": 50.0,
                "combined_odds": target["odds"],
                "avg_edge": 0.08,
                "tier": 1,
                "legs": [{
                    "match_name": target["match_name"],
                    "category": target["category"],
                    "tab_name": target["tab_name"],
                    "outcome": target["outcome_key"],
                    "raw_odds": target["odds"],
                    "btn_idx": target["btn_idx"],
                    "week": target.get("week", ""),
                    "league": "league_en",
                    "mu_phat": 0.55
                }]
            }
            success1 = bettor.execute_ticket(single_ticket, dry_fire=True)
            print(f"[*] Test 1 Result: {'PASSED' if success1 else 'FAILED'}")
        else:
            print("[-] No niche market items scraped; skipping Test 1")

        bettor.close_betslip()
        page.wait_for_timeout(1500)

        # -------------------------------------------------------------
        # TEST 2: Multi-Round / Distant Week Execution
        # -------------------------------------------------------------
        print("\n>>> TEST 2: Multi-Round Week Targeting (Primera Liga)")
        page.goto(LEAGUES["league_es"]["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        clean_page(page)

        liga_markets = extract_all_markets(page)
        # Find fixture on Week +1 or Week +2
        distinct_weeks = list(set(m.get("week", "") for m in liga_markets if m.get("week")))
        distinct_weeks.sort()
        target_week = distinct_weeks[1] if len(distinct_weeks) > 1 else (distinct_weeks[0] if distinct_weeks else "")
        week_items = [m for m in liga_markets if m.get("week") == target_week]

        if week_items:
            target2 = week_items[0]
            print(f"[+] Selected Week Target: {target2.get('week')} | {target2['match_name']} -> Odds: {target2['odds']}")
            week_ticket = {
                "type": "single",
                "stake": 30.0,
                "combined_odds": target2["odds"],
                "avg_edge": 0.07,
                "tier": 2,
                "legs": [{
                    "match_name": target2["match_name"],
                    "category": target2["category"],
                    "tab_name": target2["tab_name"],
                    "outcome": target2["outcome_key"],
                    "raw_odds": target2["odds"],
                    "btn_idx": target2["btn_idx"],
                    "week": target2.get("week", ""),
                    "league": "league_es",
                    "mu_phat": 0.50
                }]
            }
            success2 = bettor.execute_ticket(week_ticket, dry_fire=True)
            print(f"[*] Test 2 Result: {'PASSED' if success2 else 'FAILED'}")
        else:
            print("[-] No week items scraped; skipping Test 2")

        bettor.close_betslip()
        page.wait_for_timeout(1500)

        # -------------------------------------------------------------
        # TEST 3: Cross-League Smart Double Execution
        # -------------------------------------------------------------
        print("\n>>> TEST 3: Cross-League Smart Double (Premier League + Primera Liga)")
        if ou_items and week_items:
            leg_a = ou_items[0]
            leg_b = week_items[0]
            comb_odds = round(leg_a["odds"] * leg_b["odds"], 2)
            print(f"[+] Combining Leg A ({leg_a['match_name']} @ {leg_a['odds']}) + Leg B ({leg_b['match_name']} @ {leg_b['odds']}) -> {comb_odds}")

            double_ticket = {
                "type": "double",
                "stake": 25.0,
                "combined_odds": comb_odds,
                "avg_edge": 0.06,
                "tier": 2,
                "legs": [
                    {
                        "match_name": leg_a["match_name"],
                        "category": leg_a["category"],
                        "tab_name": leg_a["tab_name"],
                        "outcome": leg_a["outcome_key"],
                        "raw_odds": leg_a["odds"],
                        "btn_idx": leg_a["btn_idx"],
                        "week": leg_a.get("week", ""),
                        "league": "league_en",
                        "mu_phat": 0.52
                    },
                    {
                        "match_name": leg_b["match_name"],
                        "category": leg_b["category"],
                        "tab_name": leg_b["tab_name"],
                        "outcome": leg_b["outcome_key"],
                        "raw_odds": leg_b["odds"],
                        "btn_idx": leg_b["btn_idx"],
                        "week": leg_b.get("week", ""),
                        "league": "league_es",
                        "mu_phat": 0.50
                    }
                ]
            }
            success3 = bettor.execute_ticket(double_ticket, dry_fire=True)
            print(f"[*] Test 3 Result: {'PASSED' if success3 else 'FAILED'}")
        else:
            print("[-] Skipping Test 3 due to missing fixture legs")

        bettor.close_betslip()
        context.close()
        print("\n==================================================")
        print("[+] DRY-FIRE SUITE EXECUTION COMPLETED")
        print("==================================================")

if __name__ == "__main__":
    run_dry_fire_suite()

"""
engine/tests/backtest_tiers.py
------------------------------
Historical simulation of the tier-aware staking and smart combo strategy.

Simulates round-by-round betting across all 4 leagues using real historical
match outcomes. Mirrors the live engine logic exactly:
  - Up to 3 tickets per league per cycle (Anchor single, Smart double, Value single)
  - No combined odds cap on doubles — both legs individually cleared edge validation
  - ~35% random trigger for smart doubles (same as live engine)
  - Global cap of 10 concurrent tickets across all leagues per cycle
  - Proportional bankroll staking by tier (7% / 4% / 2.5%)
"""

import os
import sys
import random
import pandas as pd
import numpy as np
import pyarrow.parquet as pq

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from engine.config import LEAGUES, CONFIRMED_EDGES_FILE, PARQUET_DIR, BINNED_PARQUET_DIR
from football_sim.market_evaluator import get_winning_selections

def quantize_stake(amount: float) -> float:
    steps = [10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 75, 80, 90, 100, 125, 150, 200, 250, 300, 400, 500]
    clamped = min(max(amount, 10.0), 500.0)
    return float(min(steps, key=lambda x: abs(x - clamped)))

def run_backtest(initial_bankroll: float = 600.0, num_rounds: int = 150):
    print("==================================================")
    print(f"[*] RUNNING HISTORICAL BACKTEST: TIER-AWARE STRATEGY")
    print(f"[*] Initial Bankroll: ₦{initial_bankroll:,.2f} | Simulation Rounds: {num_rounds}")
    print("==================================================")

    # 1. Load confirmed edges
    df_edges = pd.read_csv(CONFIRMED_EDGES_FILE)
    edge_map = {}
    for r in df_edges.itertuples():
        edge_map[(r.league, r.match_name.strip(), r.outcome.strip())] = {
            "mu_phat": float(r.mu_phat),
            "raw_odds": float(r.raw_odds),
            "min_edge": float(r.min_edge)
        }

    # 2. Load historical match outcomes from parquets
    league_matches = {}
    for l_key in LEAGUES.keys():
        p_path = os.path.join(PARQUET_DIR, f"{l_key}.parquet")
        if not os.path.exists(p_path):
            p_path = os.path.join(BINNED_PARQUET_DIR, f"{l_key}.parquet")
        
        table = pq.read_table(p_path, columns=["id", "match_name", "home_team_score", "away_team_score", "home_team_halftime_score", "away_team_halftime_score"])
        df = table.to_pandas().sort_values("id").reset_index(drop=True)
        league_matches[l_key] = df

    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0

    total_tickets = 0
    winning_tickets = 0
    singles_placed = 0
    doubles_placed = 0
    trebles_placed = 0

    history = []

    for round_idx in range(1, num_rounds + 1):
        round_candidates = []

        # Sample matches for each league for this simulated round
        for l_key in LEAGUES.keys():
            df = league_matches[l_key]
            n_sample = LEAGUES[l_key]["matches_per_round"]
            
            # Pick a random round block
            max_start = len(df) - n_sample
            if max_start <= 0:
                continue
            start_i = random.randint(0, max_start)
            sample_df = df.iloc[start_i : start_i + n_sample]

            for _, row in sample_df.iterrows():
                m_name = row["match_name"]
                
                # Check 1X2 outcomes in edge map
                for out_key in ["1x2_1_val", "1x2_x_val", "1x2_2_val"]:
                    e_info = edge_map.get((l_key, m_name, out_key))
                    if e_info and e_info["min_edge"] >= 0.04:
                        # Determine winning status
                        winners = get_winning_selections(
                            int(row["home_team_score"]), int(row["away_team_score"]),
                            int(row["home_team_halftime_score"]), int(row["away_team_halftime_score"])
                        )
                        won = out_key in winners
                        
                        # Categorize Tier
                        # Tier 1: Edge >= 0.07 & Win Rate >= 0.45 & Odds <= 2.80
                        # Tier 2: Edge >= 0.04 & Win Rate >= 0.35 & Odds <= 3.80
                        # Tier 3: Underdogs / Speculative
                        odds = e_info["raw_odds"]
                        win_rate = e_info["mu_phat"]
                        edge = e_info["min_edge"]

                        if edge >= 0.07 and win_rate >= 0.45 and odds <= 2.80:
                            tier = 1
                        elif edge >= 0.04 and win_rate >= 0.35 and odds <= 3.80:
                            tier = 2
                        else:
                            tier = 3

                        round_candidates.append({
                            "league": l_key,
                            "match_name": m_name,
                            "outcome": out_key,
                            "raw_odds": odds,
                            "min_edge": edge,
                            "tier": tier,
                            "won": won
                        })

        if not round_candidates:
            continue

        # Sort by tier ascending (Tier 1 first), then edge descending
        round_candidates.sort(key=lambda x: (x["tier"], -x["min_edge"]))

        # Build tickets per league (up to 3 each), then enforce global cap of 10
        # Deduplicate: best edge per distinct match within each league
        unique_matches = {}
        for c in round_candidates:
            key = (c["league"], c["match_name"])
            if key not in unique_matches or c["min_edge"] > unique_matches[key]["min_edge"]:
                unique_matches[key] = c
        pool = list(unique_matches.values())

        round_tickets = []
        global_cap = 10

        for l_key in LEAGUES.keys():
            if len(round_tickets) >= global_cap:
                break

            league_pool = [c for c in pool if c["league"] == l_key]
            l_t1 = [c for c in league_pool if c["tier"] == 1]
            l_t2 = [c for c in league_pool if c["tier"] == 2]
            l_t3 = [c for c in league_pool if c["tier"] == 3]
            used = set()
            league_tickets = []

            # Priority 1: Anchor Single (Tier 1)
            if l_t1:
                anchor = l_t1[0]
                stake = quantize_stake(bankroll * 0.07)
                league_tickets.append({
                    "type": "single", "legs": [anchor],
                    "odds": anchor["raw_odds"], "stake": stake, "won": anchor["won"]
                })
                used.add(anchor["match_name"])
                singles_placed += 1

            # Priority 2: Smart Double (~35% trigger, no combined odds cap)
            if random.random() < 0.35:
                avail_anchors = [c for c in (l_t1 + l_t2) if c["match_name"] not in used]
                avail_boosters = [c for c in (l_t2 + l_t3) if c["match_name"] not in used]
                if avail_anchors and avail_boosters:
                    leg1 = avail_anchors[0]
                    for leg2 in avail_boosters:
                        if leg2["match_name"] != leg1["match_name"]:
                            comb_odds = round(leg1["raw_odds"] * leg2["raw_odds"], 2)
                            stake = quantize_stake(bankroll * 0.04)
                            league_tickets.append({
                                "type": "double", "legs": [leg1, leg2],
                                "odds": comb_odds, "stake": stake,
                                "won": leg1["won"] and leg2["won"]
                            })
                            used.add(leg1["match_name"])
                            used.add(leg2["match_name"])
                            doubles_placed += 1
                            break

            # Priority 3: Value Single (remaining T2/T3)
            for c in (l_t2 + l_t3):
                if len(league_tickets) >= 3:
                    break
                if c["match_name"] in used:
                    continue
                rate = 0.04 if c["tier"] == 2 else 0.025
                stake = quantize_stake(bankroll * rate)
                league_tickets.append({
                    "type": "single", "legs": [c],
                    "odds": c["raw_odds"], "stake": stake, "won": c["won"]
                })
                used.add(c["match_name"])
                singles_placed += 1

            # Add to round pool up to global cap
            for t in league_tickets:
                if len(round_tickets) >= global_cap:
                    break
                round_tickets.append(t)

        # 4. Settle Tickets & Update Bankroll
        for t in round_tickets:
            total_tickets += 1
            stk = t["stake"]
            if t["won"]:
                winning_tickets += 1
                profit = stk * (t["odds"] - 1.0)
                bankroll += profit
            else:
                bankroll -= stk

        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
        
        dd = (peak_bankroll - bankroll) / peak_bankroll if peak_bankroll > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

        history.append({
            "round": round_idx,
            "bankroll": bankroll,
            "peak": peak_bankroll,
            "drawdown": dd
        })

        if bankroll < 50.0:
            print(f"[!] Bankroll depleted at round {round_idx}")
            break

    # Summary Report
    net_pl = bankroll - initial_bankroll
    roi = (net_pl / initial_bankroll) * 100
    win_rate = (winning_tickets / total_tickets * 100) if total_tickets > 0 else 0

    print("==================================================")
    print("BACKTEST RESULTS & PERFORMANCE METRICS")
    print("==================================================")
    print(f"Final Bankroll:      ₦{bankroll:,.2f}")
    print(f"Peak Bankroll:       ₦{peak_bankroll:,.2f}")
    print(f"Net Profit/Loss:     {'+' if net_pl >= 0 else ''}₦{net_pl:,.2f} ({roi:+.1f}%)")
    print(f"Max Peak Drawdown:   {max_drawdown * 100:.1f}%")
    print(f"Total Tickets:       {total_tickets} (Singles: {singles_placed}, Doubles: {doubles_placed}, Trebles: {trebles_placed})")
    print(f"Ticket Win Rate:     {win_rate:.1f}%")
    print("==================================================")
    return history

if __name__ == "__main__":
    run_backtest(initial_bankroll=600.0, num_rounds=120)

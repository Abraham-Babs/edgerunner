"""
engine/tests/backtest_compare.py
---------------------------------
Runs the tier-aware backtest under three different double-cap scenarios
using the SAME random seed so results are directly comparable:

  Scenario A: Combined odds capped at 6.0  (old conservative cap)
  Scenario B: Combined odds capped at 10.0 (balanced middle ground)
  Scenario C: No combined odds cap          (fully uncapped)

All other logic is identical across scenarios.
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

def run_scenario(label: str, double_cap: float, initial_bankroll: float, num_rounds: int, seed: int):
    """Run one backtest scenario with a given combined odds cap for doubles."""
    random.seed(seed)
    np.random.seed(seed)

    # Load edges
    df_edges = pd.read_csv(CONFIRMED_EDGES_FILE)
    edge_map = {}
    for r in df_edges.itertuples():
        edge_map[(r.league, r.match_name.strip(), r.outcome.strip())] = {
            "mu_phat": float(r.mu_phat),
            "raw_odds": float(r.raw_odds),
            "min_edge": float(r.min_edge)
        }

    # Load historical matches
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
    doubles_won = 0

    for round_idx in range(1, num_rounds + 1):
        round_candidates = []

        for l_key in LEAGUES.keys():
            df = league_matches[l_key]
            n_sample = LEAGUES[l_key]["matches_per_round"]
            max_start = len(df) - n_sample
            if max_start <= 0:
                continue
            start_i = random.randint(0, max_start)
            sample_df = df.iloc[start_i : start_i + n_sample]

            for _, row in sample_df.iterrows():
                m_name = row["match_name"]
                for out_key in ["1x2_1_val", "1x2_x_val", "1x2_2_val"]:
                    e_info = edge_map.get((l_key, m_name, out_key))
                    if e_info and e_info["min_edge"] >= 0.04:
                        winners = get_winning_selections(
                            int(row["home_team_score"]), int(row["away_team_score"]),
                            int(row["home_team_halftime_score"]), int(row["away_team_halftime_score"])
                        )
                        won = out_key in winners
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
                            "league": l_key, "match_name": m_name, "outcome": out_key,
                            "raw_odds": odds, "min_edge": edge, "tier": tier, "won": won
                        })

        if not round_candidates:
            continue

        round_candidates.sort(key=lambda x: (x["tier"], -x["min_edge"]))

        # Dedup: best edge per match per league
        unique = {}
        for c in round_candidates:
            key = (c["league"], c["match_name"])
            if key not in unique or c["min_edge"] > unique[key]["min_edge"]:
                unique[key] = c
        pool = list(unique.values())

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

            # Priority 1: Anchor Single
            if l_t1:
                anchor = l_t1[0]
                stake = quantize_stake(bankroll * 0.07)
                league_tickets.append({
                    "type": "single", "legs": [anchor],
                    "odds": anchor["raw_odds"], "stake": stake, "won": anchor["won"]
                })
                used.add(anchor["match_name"])
                singles_placed += 1

            # Priority 2: Smart Double (~35% trigger)
            if random.random() < 0.35:
                avail_anchors = [c for c in (l_t1 + l_t2) if c["match_name"] not in used]
                avail_boosters = [c for c in (l_t2 + l_t3) if c["match_name"] not in used]
                if avail_anchors and avail_boosters:
                    leg1 = avail_anchors[0]
                    for leg2 in avail_boosters:
                        if leg2["match_name"] != leg1["match_name"]:
                            comb_odds = round(leg1["raw_odds"] * leg2["raw_odds"], 2)
                            # Apply the scenario's combined odds cap
                            if double_cap > 0 and comb_odds > double_cap:
                                continue  # Skip this pair, try next booster
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

            # Priority 3: Value Singles
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

            for t in league_tickets:
                if len(round_tickets) >= global_cap:
                    break
                round_tickets.append(t)

        # Settle
        for t in round_tickets:
            total_tickets += 1
            stk = t["stake"]
            if t["won"]:
                winning_tickets += 1
                if t["type"] == "double":
                    doubles_won += 1
                bankroll += stk * (t["odds"] - 1.0)
            else:
                bankroll -= stk

        if bankroll > peak_bankroll:
            peak_bankroll = bankroll
        dd = (peak_bankroll - bankroll) / peak_bankroll if peak_bankroll > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

        if bankroll < 50.0:
            break

    net_pl = bankroll - initial_bankroll
    roi = (net_pl / initial_bankroll) * 100
    win_rate = (winning_tickets / total_tickets * 100) if total_tickets > 0 else 0
    double_wr = (doubles_won / doubles_placed * 100) if doubles_placed > 0 else 0

    return {
        "label": label,
        "final": bankroll,
        "peak": peak_bankroll,
        "roi": roi,
        "max_dd": max_drawdown * 100,
        "tickets": total_tickets,
        "singles": singles_placed,
        "doubles": doubles_placed,
        "win_rate": win_rate,
        "double_wr": double_wr
    }


if __name__ == "__main__":
    SEED = 42
    BANK = 600.0
    ROUNDS = 120

    scenarios = [
        ("Cap 6.0 (old)", 6.0),
        ("Cap 10.0 (balanced)", 10.0),
        ("Uncapped", 0),   # 0 = no cap
    ]

    results = []
    for label, cap in scenarios:
        r = run_scenario(label, double_cap=cap, initial_bankroll=BANK, num_rounds=ROUNDS, seed=SEED)
        results.append(r)

    # Print comparison table
    print("\n" + "=" * 90)
    print("BACKTEST COMPARISON: COMBINED ODDS CAP SCENARIOS")
    print("=" * 90)
    print(f"{'Metric':<22} {'Cap 6.0 (old)':>20} {'Cap 10.0 (balanced)':>20} {'Uncapped':>20}")
    print("-" * 90)

    for key, fmt, label in [
        ("final",     "₦{:,.0f}", "Final Bankroll"),
        ("roi",       "{:+,.1f}%", "ROI"),
        ("max_dd",    "{:.1f}%",   "Max Drawdown"),
        ("tickets",   "{}",        "Total Tickets"),
        ("singles",   "{}",        "Singles"),
        ("doubles",   "{}",        "Doubles"),
        ("win_rate",  "{:.1f}%",   "Win Rate"),
        ("double_wr", "{:.1f}%",   "Double Win Rate"),
    ]:
        vals = [fmt.format(r[key]) for r in results]
        print(f"{label:<22} {vals[0]:>20} {vals[1]:>20} {vals[2]:>20}")

    print("=" * 90)

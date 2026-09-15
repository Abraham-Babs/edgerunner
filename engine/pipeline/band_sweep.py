"""
engine/pipeline/band_sweep.py
------------------------------
Runs walkforward edge validation across all 4 leagues and evaluates
out-of-sample ROI and t-stats broken down by odds buckets and outcome types.
"""

import os
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from engine.config import LEAGUES, ODDS_FILE, PARQUET_DIR, BINNED_PARQUET_DIR
from engine.pipeline.walkforward import walkforward_edges

def run_sweep():
    with open(ODDS_FILE, "r", encoding="utf-8") as f:
        odds_db = json.load(f)

    all_dfs = []
    cols = ["id", "match_name", "home_team_score", "away_team_score"]

    for league in LEAGUES.keys():
        p_path = os.path.join(PARQUET_DIR, f"{league}.parquet")
        if not os.path.exists(p_path):
            p_path = os.path.join(BINNED_PARQUET_DIR, f"{league}.parquet")
        if not os.path.exists(p_path):
            continue

        df = pq.read_table(p_path, columns=cols).to_pandas()
        l_odds = odds_db.get(league, {})
        wf = walkforward_edges(df, l_odds, league)
        if not wf.empty:
            all_dfs.append(wf)

    if not all_dfs:
        print("No walk-forward edges found.")
        return

    full = pd.concat(all_dfs, ignore_index=True)

    bins = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 100.0]
    labels = ["1.0-1.5", "1.5-2.0", "2.0-2.5", "2.5-3.0", "3.0-4.0", "4.0+"]
    full["odds_bucket"] = pd.cut(full["raw_odds"], bins=bins, labels=labels, right=False)

    def categorize_outcome(o):
        if o in ["H", "D", "A"]:
            return "1X2"
        elif o.startswith("O") or o.startswith("U"):
            return "Totals (O/U)"
        elif o in ["GG", "NG"]:
            return "BTTS"
        return "Other"

    full["market_type"] = full["outcome"].apply(categorize_outcome)

    print("\n" + "="*85)
    print("WALK-FORWARD PERFORMANCE BY LEAGUE & ODDS BUCKET")
    print("="*85)

    for league, lg_df in full.groupby("league"):
        print(f"\n--- League: {league} ({LEAGUES[league]['name']}) ---")
        summary = lg_df.groupby("odds_bucket", observed=False).agg(
            n_edges=("oos_roi", "count"),
            mean_oos_roi=("oos_roi", lambda x: f"{x.mean()*100:+.2f}%" if len(x) > 0 else "N/A"),
            median_oos_roi=("oos_roi", lambda x: f"{x.median()*100:+.2f}%" if len(x) > 0 else "N/A"),
            mean_t_stat=("oos_t_stat", lambda x: f"{x.mean():.2f}" if len(x.dropna()) > 0 else "N/A"),
            pct_pos_roi=("oos_roi", lambda x: f"{(x > 0).mean()*100:.1f}%" if len(x) > 0 else "N/A"),
            t_stat_ge_2=("oos_t_stat", lambda x: f"{(x >= 2.0).sum()}/{len(x)}" if len(x) > 0 else "N/A"),
        )
        print(summary.to_string())

    print("\n" + "="*85)
    print("WALK-FORWARD PERFORMANCE BY LEAGUE & MARKET TYPE")
    print("="*85)

    for league, lg_df in full.groupby("league"):
        print(f"\n--- League: {league} ({LEAGUES[league]['name']}) ---")
        summary_mkt = lg_df.groupby("market_type", observed=False).agg(
            n_edges=("oos_roi", "count"),
            mean_oos_roi=("oos_roi", lambda x: f"{x.mean()*100:+.2f}%" if len(x) > 0 else "N/A"),
            mean_t_stat=("oos_t_stat", lambda x: f"{x.mean():.2f}" if len(x.dropna()) > 0 else "N/A"),
            pct_pos_roi=("oos_roi", lambda x: f"{(x > 0).mean()*100:.1f}%" if len(x) > 0 else "N/A"),
            t_stat_ge_2=("oos_t_stat", lambda x: f"{(x >= 2.0).sum()}/{len(x)}" if len(x) > 0 else "N/A"),
        )
        print(summary_mkt.to_string())

if __name__ == "__main__":
    run_sweep()

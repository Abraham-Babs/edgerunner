"""
engine/pipeline/edge_compiler.py
--------------------------------
Full dynamic pipeline that ingests:
1. Updated historical match outcomes (from parquets/cat_*.parquet)
2. Fresh bookmaker odds (from h2h_odds.json)
3. Fits empirical hit rates (mu_phat) and model bin edges (geom_fit_17, geom_fit_27)
4. Exports an updated analysis/results/confirmed_edges.csv
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# Setup paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from engine.config import (
    LEAGUES, ODDS_FILE, CONFIRMED_EDGES_FILE, 
    PARQUET_DIR, BINNED_PARQUET_DIR, LOOKUP_DIR, RESULTS_DIR
)
from football_sim.market_evaluator import get_winning_selections
from engine.pipeline.walkforward import walkforward_edges, OUTCOME_MARKET_MAP

MIN_HITS = 30

def all_outcome_keys() -> list:
    keys = set()
    for hg in range(7):
        for ag in range(7):
            for h_ht in range(hg + 1):
                for a_ht in range(ag + 1):
                    keys |= get_winning_selections(hg, ag, h_ht, a_ht)
    return sorted(keys)

ALL_OUTCOMES = all_outcome_keys()

def flatten_odds(odds_db: dict, league: str) -> pd.DataFrame:
    rows = []
    for match, markets in odds_db.get(league, {}).items():
        for market, selections in markets.items():
            for outcome_key, vals in selections.items():
                if isinstance(vals, dict) and "fair_prob" in vals:
                    rows.append({
                        "match_name": match,
                        "outcome": outcome_key,
                        "fair_prob": vals["fair_prob"],
                        "raw_odds": vals.get("raw"),
                    })
    return pd.DataFrame(rows)

def load_geom_edges(league: str, grid: str, odds_df: pd.DataFrame, lookup_df: pd.DataFrame) -> pd.DataFrame:
    """Load geom_fit_{grid}_{league}.csv and compute grid-level edge."""
    fit_path = os.path.join(RESULTS_DIR, f"geom_fit_{grid}_{league}.csv")
    if not os.path.exists(fit_path):
        return pd.DataFrame()
        
    phat_df = pd.read_csv(fit_path, usecols=["state_id", "outcome", "p_hat"])
    state_col = f"state_{grid}_id"
    matchups = lookup_df[["match_name", state_col]].rename(columns={state_col: "state_id"})
    
    m_odds = matchups.merge(odds_df, on="match_name", how="inner")
    merged = m_odds.merge(phat_df, on=["state_id", "outcome"], how="inner")
    merged[f"bin{grid}_edge"] = (merged["p_hat"] - merged["fair_prob"]).round(6)
    return merged[["match_name", "outcome", f"bin{grid}_edge"]]

def compile_league_edges(league: str, odds_db: dict) -> pd.DataFrame:
    lookup_file = LEAGUES[league]["lookup"]
    lookup_path = os.path.join(LOOKUP_DIR, lookup_file)
    
    # Priority: read parquets/ if present, fallback to binned_parquets/
    primary_parquet = os.path.join(PARQUET_DIR, f"{league}.parquet")
    fallback_parquet = os.path.join(BINNED_PARQUET_DIR, f"{league}.parquet")
    parquet_path = primary_parquet if os.path.exists(primary_parquet) else fallback_parquet
    
    lookup = pq.read_table(lookup_path, columns=["match_name", "state_17_id", "state_27_id"]).to_pandas()
    active_matches = set(lookup["match_name"])
    
    cols = ["id", "match_name", "home_team_score", "away_team_score", "home_team_halftime_score", "away_team_halftime_score"]
    df = pq.read_table(parquet_path, columns=cols).to_pandas()
    df.sort_values("id", inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    df = df[df["match_name"].isin(active_matches)].reset_index(drop=True)
    print(f"[*] Processing [{league}]: {len(df):,} match rows across {df['match_name'].nunique()} active fixtures...")
    
    # Settle binary matrix
    n = len(df)
    n_out = len(ALL_OUTCOMES)
    outcome_idx = {o: i for i, o in enumerate(ALL_OUTCOMES)}
    matrix = np.zeros((n, n_out), dtype=np.int8)
    
    for i, row in enumerate(df.itertuples(index=False)):
        winners = get_winning_selections(
            int(row.home_team_score), int(row.away_team_score),
            int(row.home_team_halftime_score), int(row.away_team_halftime_score),
        )
        for o in winners:
            if o in outcome_idx:
                matrix[i, outcome_idx[o]] = 1
                
    match_names = df["match_name"].values
    unique_matches = sorted(active_matches)
    records = []
    
    for match in unique_matches:
        mask = (match_names == match)
        total_trials = int(mask.sum())
        if total_trials == 0:
            continue
        hit_counts = matrix[mask].sum(axis=0)
        for j, outcome in enumerate(ALL_OUTCOMES):
            hits = int(hit_counts[j])
            if hits < MIN_HITS:
                continue
            records.append({
                "match_name": match,
                "outcome": outcome,
                "total_trials": total_trials,
                "total_hits": hits,
                "mu_phat": round(hits / total_trials, 6),
            })
            
    res_df = pd.DataFrame(records)
    if res_df.empty:
        return pd.DataFrame()
        
    odds_df = flatten_odds(odds_db, league)
    merged = res_df.merge(odds_df, on=["match_name", "outcome"], how="inner")
    merged = merged.merge(lookup, on="match_name", how="left")
    
    merged["mu_edge"] = (merged["mu_phat"] - merged["fair_prob"]).round(6)
    
    # Merge bin-17 and bin-27 model edges
    b17 = load_geom_edges(league, "17", odds_df, lookup)
    b27 = load_geom_edges(league, "27", odds_df, lookup)
    
    if not b17.empty:
        merged = merged.merge(b17, on=["match_name", "outcome"], how="left")
    else:
        merged["bin17_edge"] = merged["mu_edge"]
        
    if not b27.empty:
        merged = merged.merge(b27, on=["match_name", "outcome"], how="left")
    else:
        merged["bin27_edge"] = merged["mu_edge"]
        
    merged["min_edge"] = merged[["mu_edge", "bin17_edge", "bin27_edge"]].min(axis=1).round(6)
    merged["league"] = league
    
    # Walk-forward out-of-sample edge validation
    wf_df = walkforward_edges(df, odds_db.get(league, {}), league)
    if not wf_df.empty:
        map_dict = {k: v[1] for k, v in OUTCOME_MARKET_MAP.items()}
        wf_df["outcome"] = wf_df["outcome"].map(map_dict)
        wf_cols = ["match_name", "outcome", "oos_roi", "oos_t_stat", "n_train", "n_test"]
        merged = merged.merge(wf_df[wf_cols], on=["match_name", "outcome"], how="left")
    else:
        for c in ["oos_roi", "oos_t_stat", "n_train", "n_test"]:
            merged[c] = np.nan
    
    # Re-order columns to match confirmed_edges format
    ordered_cols = [
        "league", "match_name", "outcome", "mu_phat", "fair_prob", "raw_odds",
        "mu_edge", "bin17_edge", "bin27_edge", "min_edge", "state_17_id", "state_27_id",
        "oos_roi", "oos_t_stat", "n_train", "n_test"
    ]
    merged = merged[[c for c in ordered_cols if c in merged.columns]]
    pos = merged[(merged["min_edge"] > 0) & (merged["oos_t_stat"].notna()) & (merged["oos_t_stat"] >= 2.0)].copy()
    pos.sort_values("min_edge", ascending=False, inplace=True)
    return pos

def run_edge_compilation():
    print("==================================================")
    print("[*] STARTING LIVE EDGE COMPILATION PIPELINE")
    print("==================================================")
    if not os.path.exists(ODDS_FILE):
        print(f"[-] ERROR: Odds file not found: {ODDS_FILE}")
        return False
        
    with open(ODDS_FILE, "r", encoding="utf-8") as f:
        odds_db = json.load(f)
        
    all_leagues = []
    for league in LEAGUES.keys():
        try:
            df = compile_league_edges(league, odds_db)
            if not df.empty:
                all_leagues.append(df)
                print(f"[+] [{league}] Compiled {len(df):,} positive edges across {df['match_name'].nunique()} matchups")
        except Exception as e:
            print(f"[-] Error compiling {league}: {e}")
            
    if not all_leagues:
        print("[-] No edges compiled.")
        return False
        
    final_df = pd.concat(all_leagues, ignore_index=True)
    final_df.sort_values("min_edge", ascending=False, inplace=True)
    os.makedirs(os.path.dirname(CONFIRMED_EDGES_FILE), exist_ok=True)
    final_df.to_csv(CONFIRMED_EDGES_FILE, index=False)
    print("==================================================")
    print(f"[+] SUCCESS: Saved {len(final_df):,} confirmed edges to {CONFIRMED_EDGES_FILE}")
    print("==================================================")
    return True

if __name__ == "__main__":
    run_edge_compilation()

"""
run.py — Main execution runner for the 4-league football simulation engine.
"""
import os
import sys
import pandas as pd

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from data_loader import FootballDataLoader
from sim_engine import FootballSimEngine
from strategies.engine_edge import EngineEdgeStrategy

LEAGUES = {
    "league_en": "England (Premier League)",
    "league_es": "Spain (La Liga)",
    "league_it": "Italy (Serie A)",
    "league_de": "Germany (Bundesliga)",
}


def main():
    loader = FootballDataLoader()
    results_dir = os.path.join(current_dir, "results")
    os.makedirs(results_dir, exist_ok=True)

    strategies = [
        EngineEdgeStrategy(name="EngineEdge_3pct", edge_threshold=0.03, stake=50.0),
        EngineEdgeStrategy(name="EngineEdge_5pct", edge_threshold=0.05, stake=50.0),
        EngineEdgeStrategy(name="EngineEdge_7pct", edge_threshold=0.07, stake=50.0),
    ]

    all_summaries = []

    print(f"\n{'='*75}")
    print(f"{'FOOTBALL SIMULATION ENGINE — 4 LEAGUE BACKTEST':^75}")
    print(f"{'='*75}\n")

    for league_key, league_name in LEAGUES.items():
        print(f"Loading {league_name} ({league_key})...")
        matches_df, odds_dict = loader.load_league(league_key)
        print(f"  Matches loaded: {len(matches_df):,} | Matches with odds: {len(odds_dict):,}")

        for strat in strategies:
            engine = FootballSimEngine(starting_balance=5000.0, min_stake=10.0)
            res = engine.run(strat, matches_df, odds_dict, record_log=False)
            res["league_key"] = league_key
            res["league_name"] = league_name
            all_summaries.append(res)

    df_results = pd.DataFrame(all_summaries)
    cols = [
        "league_key",
        "strategy",
        "net_pl",
        "roi_pct",
        "win_rate_pct",
        "max_drawdown_pct",
        "profit_factor",
        "total_bets",
        "won_bets",
        "total_wagered",
        "final_balance",
    ]
    df_display = df_results[cols].sort_values(by="net_pl", ascending=False)

    summary_file = os.path.join(results_dir, "summary.csv")
    df_display.to_csv(summary_file, index=False)

    print("\n" + "=" * 75)
    print("BACKTEST RESULTS (SORTED BY NET P/L)")
    print("=" * 75)
    print(df_display.to_string(index=False))
    print("=" * 75)
    print(f"\nFull results exported to: {summary_file}\n")


if __name__ == "__main__":
    main()

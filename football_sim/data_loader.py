"""
data_loader.py — Unified loader for football match data, engine lookup lambdas, and market odds.
"""
import json
import os
from typing import Dict, Tuple
import duckdb
import pandas as pd

LOOKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lookup"))
PARQUET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "parquets"))
ODDS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "h2h_odds.json"))

LEAGUE_LOOKUP_FILES = {
    "league_en": "matchup_lambdas_league_en.parquet",
    "league_es": "matchup_lambdas_league_es.parquet",
    "league_it": "matchup_lambdas_league_it.parquet",
    "league_de": "matchup_lambdas_league_de.parquet",
}


class FootballDataLoader:
    def __init__(self, odds_path: str = ODDS_FILE):
        with open(odds_path, "r", encoding="utf-8") as f:
            self.all_odds: Dict = json.load(f)

    def load_league(self, league_key: str) -> Tuple[pd.DataFrame, Dict[str, dict]]:
        """
        Loads match parquets joined with model lookup lambdas and states,
        and returns (matches_df, league_odds_dict).
        """
        parquet_file = os.path.join(PARQUET_DIR, f"{league_key}.parquet")
        lookup_file = os.path.join(LOOKUP_DIR, LEAGUE_LOOKUP_FILES[league_key])

        query = f"""
            SELECT 
                m.id,
                m.match_id,
                m.match_date,
                m.match_name,
                m.home_team_name,
                m.away_team_name,
                m.home_team_score,
                m.away_team_score,
                m.home_team_halftime_score,
                m.away_team_halftime_score,
                l.lambda_bin_17,
                l.lambda_bin_27,
                l.param_lambda_home_ft,
                l.param_lambda_away_ft,
                l.param_lambda_home_ht,
                l.param_lambda_away_ht,
                l.odds_lambda_home_ft,
                l.odds_lambda_away_ft
            FROM '{parquet_file}' m
            LEFT JOIN '{lookup_file}' l ON m.match_name = l.match_name
            ORDER BY m.id ASC
        """
        df = duckdb.query(query).df()
        odds = self.all_odds.get(league_key, {})
        return df, odds

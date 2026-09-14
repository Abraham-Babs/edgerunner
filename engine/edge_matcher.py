"""
engine/edge_matcher.py
----------------------
The gatekeeper. Before any bet is placed, this module checks whether the
match and odds currently on screen align with a statistically confirmed edge
from our historical data.

How it works:
  - Loads a pre-compiled table of edges from 'confirmed_edges.csv'. Each row
    in that file represents a match type (e.g. 'MAN - ARS', home win) where
    historical data shows the true win probability is meaningfully higher than
    what the bookmaker's odds imply.
  - Applies a profile filter (conservative / balanced / expansive) to control
    how strict the minimum edge, win rate, and odds requirements are.
  - Watches the source odds file (h2h_odds.json) for any updates. If the file
    changes (i.e. fresh odds data has been pulled), it automatically triggers
    a re-compilation and reloads the edge table into memory — no restart needed.
  - Provides two lookup methods:
      find_edge()       : Check if a specific match + outcome has a confirmed edge.
      get_matchup_edges(): Get all confirmed edges for a given match, ranked by
                          strength.
"""

import os
import sys
import pandas as pd
from typing import Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from engine.config import CONFIRMED_EDGES_FILE, ODDS_FILE, PROFILES
from engine.pipeline.edge_compiler import run_edge_compilation

class EdgeMatcher:
    def __init__(self, profile_name: str = "balanced"):
        self.profile_name = profile_name
        self.profile = PROFILES.get(profile_name, PROFILES["balanced"])
        self.edges_mtime: float = 0.0
        self.odds_mtime: float = 0.0
        self.lookup: Dict[Tuple[str, str, str], dict] = {}
        self.load_edges(force=True)

    def check_and_reload(self):
        """Check if upstream h2h_odds.json or confirmed_edges.csv has updated."""
        needs_compile = False
        if os.path.exists(ODDS_FILE):
            curr_odds_mtime = os.path.getmtime(ODDS_FILE)
            if curr_odds_mtime > self.odds_mtime and self.odds_mtime > 0:
                print("[*] Detected fresh h2h_odds.json! Triggering edge re-compilation...")
                needs_compile = True
            self.odds_mtime = curr_odds_mtime

        if needs_compile or not os.path.exists(CONFIRMED_EDGES_FILE):
            run_edge_compilation()

        if os.path.exists(CONFIRMED_EDGES_FILE):
            curr_edges_mtime = os.path.getmtime(CONFIRMED_EDGES_FILE)
            if curr_edges_mtime > self.edges_mtime:
                print("[*] Reloading in-memory edge table from confirmed_edges.csv...")
                self.load_edges(force=True)

    def load_edges(self, force: bool = False):
        if not os.path.exists(CONFIRMED_EDGES_FILE):
            print("[-] confirmed_edges.csv does not exist. Running initial compilation...")
            run_edge_compilation()

        if not os.path.exists(CONFIRMED_EDGES_FILE):
            print("[-] Unable to load edges: file missing.")
            return

        self.edges_mtime = os.path.getmtime(CONFIRMED_EDGES_FILE)
        if os.path.exists(ODDS_FILE):
            self.odds_mtime = os.path.getmtime(ODDS_FILE)

        self.df = pd.read_csv(CONFIRMED_EDGES_FILE)
        self.lookups: Dict[str, Dict[Tuple[str, str, str], dict]] = {}
        for p_name, p_cfg in PROFILES.items():
            min_e = p_cfg["min_edge"]
            min_w = p_cfg["min_win_rate"]
            min_o = p_cfg.get("min_odds", 1.0)
            max_o = p_cfg["max_odds"]
            f = self.df[
                (self.df["min_edge"] >= min_e) &
                (self.df["mu_phat"] >= min_w) &
                (self.df["raw_odds"] >= min_o) &
                (self.df["raw_odds"] <= max_o)
            ]
            lookup = {}
            for row in f.itertuples(index=False):
                key = (row.league, row.match_name.strip(), row.outcome.strip())
                lookup[key] = {
                    "league": row.league,
                    "match_name": row.match_name.strip(),
                    "outcome": row.outcome.strip(),
                    "mu_phat": float(row.mu_phat),
                    "fair_prob": float(row.fair_prob),
                    "raw_odds": float(row.raw_odds),
                    "min_edge": float(row.min_edge)
                }
            self.lookups[p_name] = lookup

        self.lookup = self.lookups.get(self.profile_name, self.lookups.get("ultra_conservative", {}))
        print(f"[+] Loaded multi-profile edge tables: Ultra-Conservative ({len(self.lookups.get('ultra_conservative', {})):,}), Conservative ({len(self.lookups.get('conservative', {})):,}), Balanced ({len(self.lookups.get('balanced', {})):,})")

    def set_profile(self, profile_name: str):
        if profile_name in self.lookups:
            self.profile_name = profile_name
            self.profile = PROFILES.get(profile_name, PROFILES["ultra_conservative"])
            self.lookup = self.lookups[profile_name]

    def find_edge(self, league: str, match_name: str, outcome_key: str, profile_name: Optional[str] = None) -> Optional[dict]:
        """Lookup positive edge for a given league, matchup, and outcome."""
        target_lookup = self.lookups.get(profile_name, self.lookup) if profile_name else self.lookup
        return target_lookup.get((league, match_name.strip(), outcome_key.strip()))

    def get_matchup_edges(self, league: str, match_name: str, profile_name: Optional[str] = None) -> List[dict]:
        """Return all valid positive edges for a given match, sorted by highest edge."""
        target_lookup = self.lookups.get(profile_name, self.lookup) if profile_name else self.lookup
        matches = []
        for (l, m, o), edge_info in target_lookup.items():
            if l == league and m == match_name.strip():
                matches.append(edge_info)
        matches.sort(key=lambda x: x["min_edge"], reverse=True)
        return matches


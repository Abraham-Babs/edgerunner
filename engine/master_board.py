"""
engine/master_board.py
-----------------------
Maintains an in-memory rolling sliding window cache of positive-EV edges across
all 4 virtual football leagues (Premier League, Primera Liga, Serie League, Bundes League).

Features:
1. Retains already-scraped active weeks in memory.
2. Tracks exact kickoff epoch per round to prevent any expired match selection.
3. Automatically prunes concluded or kicked-off rounds.
4. Provides instant eviction if a platform banner indicates round expiry.
5. Flattens active candidate edges into a unified cross-league board.
"""

import time
from typing import Dict, List, Any, Set, Optional

class MasterBoard:
    def __init__(self):
        # Key: f"{league_key} | {week_str}" -> {"edges": List[dict], "kickoff_epoch": float}
        self._board: Dict[str, Dict[str, Any]] = {}

    def get_cached_weeks(self, league_key: str) -> Set[str]:
        """Returns the set of week identifiers currently cached for this league."""
        prefix = f"{league_key} | "
        now = time.time()
        cached = set()
        for k, v in self._board.items():
            if k.startswith(prefix):
                # Filter out expired rounds
                ko = v.get("kickoff_epoch", 0.0)
                if ko == 0.0 or now < ko:
                    cached.add(k[len(prefix):])
        return cached

    def has_week(self, league_key: str, week: str) -> bool:
        """Returns True if the specified league and week are already cached and unexpired."""
        key = f"{league_key} | {week}"
        if key not in self._board:
            return False
        ko = self._board[key].get("kickoff_epoch", 0.0)
        if ko > 0.0 and time.time() >= ko:
            self._board.pop(key, None)
            return False
        return True

    def set_week_edges(self, league_key: str, week: str, edges: List[Dict[str, Any]], kickoff_epoch: float = 0.0):
        """Sets or replaces the positive-EV candidate edges and kickoff timestamp for a round."""
        for e in edges:
            e["kickoff_epoch"] = kickoff_epoch
        self._board[f"{league_key} | {week}"] = {
            "edges": edges,
            "kickoff_epoch": kickoff_epoch
        }

    def evict_week(self, league_key: str, week: str):
        """Immediately removes a week from memory (e.g. when platform signals expired)."""
        key = f"{league_key} | {week}"
        if key in self._board:
            print(f"[*] Master Board: Evicted {key} (round expired/concluded).")
            self._board.pop(key, None)

    def prune_expired_weeks(self, league_key: str, visible_weeks: Set[str]):
        """
        Removes any cached weeks for this league that are no longer visible on screen
        or whose kickoff time has elapsed.
        """
        prefix = f"{league_key} | "
        now = time.time()
        to_remove = []
        for k, v in self._board.items():
            if k.startswith(prefix):
                w = k[len(prefix):]
                ko = v.get("kickoff_epoch", 0.0)
                if (visible_weeks and w not in visible_weeks) or (ko > 0.0 and now >= ko):
                    to_remove.append(k)
        for k in to_remove:
            self._board.pop(k, None)

    def get_all_candidates(self) -> List[Dict[str, Any]]:
        """
        Returns a flat list of all active positive-EV edges across all leagues and weeks,
        strictly filtering out any matches whose kickoff has arrived.
        """
        all_edges = []
        now = time.time()
        for v in self._board.values():
            ko = v.get("kickoff_epoch", 0.0)
            if ko == 0.0 or now < ko:
                all_edges.extend(v.get("edges", []))
        return all_edges

    def total_count(self) -> int:
        return len(self.get_all_candidates())

    def clear(self):
        """Clears the board completely."""
        self._board.clear()

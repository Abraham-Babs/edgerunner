"""
engine/master_board.py
-----------------------
Maintains an in-memory rolling sliding window cache of positive-EV edges across
all 4 virtual football leagues (Premier League, Primera Liga, Serie League, Bundes League).

Completely decoupled from Playwright:
1. Ingests candidate models and server-aligned rounds directly from discovery client.
2. Tracks exact kickoff epoch per round using server-skew-aligned timestamps.
3. Automatically prunes kicked-off or expired rounds.
4. Flattens active candidates across all leagues for cross-league ticket construction.
"""

import time
from typing import Dict, List, Any, Set, Optional

class MasterBoard:
    def __init__(self):
        # Key: f"{league_key} | {week_str}" -> {"edges": List[dict], "kickoff_epoch": float, "round_id": str}
        self._board: Dict[str, Dict[str, Any]] = {}
        self.last_sync_epoch: float = 0.0

    def sync_from_discovery(self, discovery_payload: Dict[str, Any]):
        """
        Updates the MasterBoard directly from PublicDiscoveryClient output.
        discovery_payload schema:
          {
            "leagues": {
              league_key: {
                "rounds": { week_str: {"round_id": ..., "kickoff_epoch": ..., ...} },
                "candidates": [...]
              }
            },
            "server_epoch": float
          }
        """
        server_epoch = discovery_payload.get("server_epoch", time.time())
        self.last_sync_epoch = server_epoch
        leagues = discovery_payload.get("leagues", {})

        for l_key, l_data in leagues.items():
            rounds = l_data.get("rounds", {})
            candidates = l_data.get("candidates", [])
            visible_weeks = set(rounds.keys())

            # 1. Prune concluded or non-visible rounds for this league
            self.prune_expired_weeks(l_key, visible_weeks, server_epoch=server_epoch)

            # 2. Group candidates by week
            by_week: Dict[str, List[dict]] = {w: [] for w in visible_weeks}
            for cand in candidates:
                w = cand.get("week")
                if w in by_week:
                    by_week[w].append(cand)

            # 3. Update board for each visible round
            for w, w_meta in rounds.items():
                ko = w_meta.get("kickoff_epoch", 0.0)
                if ko > 0.0 and server_epoch >= ko:
                    continue  # Already kicked off
                self.set_week_edges(
                    league_key=l_key,
                    week=w,
                    edges=by_week.get(w, []),
                    kickoff_epoch=ko,
                    round_id=w_meta.get("round_id")
                )

    def get_cached_weeks(self, league_key: str, server_epoch: Optional[float] = None) -> Set[str]:
        """Returns the set of unexpired week identifiers currently cached for this league."""
        prefix = f"{league_key} | "
        now = server_epoch or time.time()
        cached = set()
        for k, v in self._board.items():
            if k.startswith(prefix):
                ko = v.get("kickoff_epoch", 0.0)
                if ko == 0.0 or now < ko:
                    cached.add(k[len(prefix):])
        return cached

    def has_week(self, league_key: str, week: str, server_epoch: Optional[float] = None) -> bool:
        """Returns True if the specified league and week are already cached and unexpired."""
        key = f"{league_key} | {week}"
        if key not in self._board:
            return False
        ko = self._board[key].get("kickoff_epoch", 0.0)
        now = server_epoch or time.time()
        if ko > 0.0 and now >= ko:
            self._board.pop(key, None)
            return False
        return True

    def set_week_edges(
        self,
        league_key: str,
        week: str,
        edges: List[Dict[str, Any]],
        kickoff_epoch: float = 0.0,
        round_id: Optional[str] = None
    ):
        """Sets or replaces candidate edges and metadata for a specific league round."""
        for e in edges:
            e["kickoff_epoch"] = kickoff_epoch
            if round_id and "round_id" not in e:
                e["round_id"] = round_id
        self._board[f"{league_key} | {week}"] = {
            "edges": edges,
            "kickoff_epoch": kickoff_epoch,
            "round_id": round_id,
        }

    def evict_week(self, league_key: str, week: str):
        """Immediately removes a week from memory (e.g. when platform signals round concluded)."""
        key = f"{league_key} | {week}"
        if key in self._board:
            print(f"[*] Master Board: Evicted {key} (round expired/concluded).")
            self._board.pop(key, None)

    def prune_expired_weeks(self, league_key: str, visible_weeks: Set[str], server_epoch: Optional[float] = None):
        """Removes cached rounds that are no longer active or whose kickoff has arrived."""
        prefix = f"{league_key} | "
        now = server_epoch or time.time()
        to_remove = []
        for k, v in self._board.items():
            if k.startswith(prefix):
                w = k[len(prefix):]
                ko = v.get("kickoff_epoch", 0.0)
                if (visible_weeks and w not in visible_weeks) or (ko > 0.0 and now >= ko):
                    to_remove.append(k)
        for k in to_remove:
            self._board.pop(k, None)

    def get_all_candidates(self, server_epoch: Optional[float] = None) -> List[Dict[str, Any]]:
        """Returns flat list of all active candidates strictly filtering out expired kickoffs."""
        all_edges = []
        now = server_epoch or time.time()
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

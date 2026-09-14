"""
engine/scheduler.py
-------------------
Asynchronous Multi-League Scheduler:
1. Tracks independent countdown timers for:
   - Premier League (England) ~180s cycle
   - Primera Liga (Spain) ~180s cycle
   - Serie League (Italy) ~180s cycle
   - Bundes League (Germany) ~90s cycle
2. Prioritizes visiting whichever league is in the optimal pre-kickoff window (25s - 50s before kickoff).
3. Non-linear navigation prevents robotic sequential loop patterns.
"""

import time
from typing import Dict, List, Optional
from engine.config import LEAGUES

class MultiLeagueScheduler:
    def __init__(self, league_keys: Optional[List[str]] = None):
        self.active_leagues = league_keys or list(LEAGUES.keys())
        # State tracking: league -> {"next_kickoff": float, "last_visited": float}
        self.state: Dict[str, dict] = {}
        now = time.time()
        for l in self.active_leagues:
            interval = LEAGUES[l]["round_cycle_sec"]
            self.state[l] = {
                "estimated_cycle": interval,
                "next_kickoff": now + interval,
                "last_visited": 0.0
            }

    def update_league_timer(self, league: str, remaining_seconds: int):
        """Update live observed countdown from the UI."""
        if league in self.state:
            now = time.time()
            self.state[league]["next_kickoff"] = now + remaining_seconds
            self.state[league]["last_visited"] = now

    def get_next_league_target(self) -> str:
        """
        Determines which league to visit next:
        Picks the league whose kickoff is closest, provided it is not already in-play (< 15s).
        """
        now = time.time()
        best_league = None
        min_time_to_kickoff = float("inf")

        for l in self.active_leagues:
            t_left = self.state[l]["next_kickoff"] - now
            # If round has passed, reset estimate
            if t_left <= 0:
                t_left = self.state[l]["estimated_cycle"]
                self.state[l]["next_kickoff"] = now + t_left

            # Look for closest upcoming round with adequate betting buffer (> 15s)
            if 15 < t_left < min_time_to_kickoff:
                min_time_to_kickoff = t_left
                best_league = l

        # Fallback to the league not visited longest
        if not best_league:
            best_league = min(self.active_leagues, key=lambda x: self.state[x]["last_visited"])

        return best_league

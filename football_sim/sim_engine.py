"""
sim_engine.py — High-performance scoring, bankroll tracking, and metrics calculation engine.
Uses matchup-level prediction caching and fast array extraction for multi-million row scale.
"""
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from market_evaluator import get_winning_selections
from prediction_engine import BaseFootballStrategy

MIN_STAKE = 10.0


class FootballSimEngine:
    def __init__(self, starting_balance: float = 5000.0, min_stake: float = MIN_STAKE):
        self.starting_balance = starting_balance
        self.min_stake = min_stake

    def run(
        self,
        strategy: BaseFootballStrategy,
        matches_df: pd.DataFrame,
        odds_dict: Dict[str, dict],
        record_log: bool = False,
    ) -> Dict[str, Any]:
        balance = self.starting_balance
        peak_balance = balance
        max_drawdown = 0.0

        n_matches = len(matches_df)
        matches_bet = 0
        total_bets = 0
        won_bets = 0
        total_wagered = 0.0
        gross_wins = 0.0
        gross_losses = 0.0

        log = [] if record_log else None

        # Pre-cache strategy predictions by unique matchup info to avoid 1M+ redundant calculations
        unique_matchups = matches_df.drop_duplicates(subset=["match_name"]).to_dict(orient="records")
        bets_cache: Dict[str, List] = {}
        for row in unique_matchups:
            m_name = row["match_name"]
            m_odds = odds_dict.get(m_name)
            if m_odds:
                bets = strategy.predict(row, m_odds)
                if bets:
                    bets_cache[m_name] = bets

        # Fast array extractions
        match_names = matches_df["match_name"].to_numpy()
        hg_arr = matches_df["home_team_score"].to_numpy(dtype=np.int16)
        ag_arr = matches_df["away_team_score"].to_numpy(dtype=np.int16)
        h_ht_arr = matches_df["home_team_halftime_score"].to_numpy(dtype=np.int16)
        a_ht_arr = matches_df["away_team_halftime_score"].to_numpy(dtype=np.int16)

        for i in range(n_matches):
            if balance < self.min_stake:
                break

            m_name = match_names[i]
            bets = bets_cache.get(m_name)
            if not bets:
                continue

            req_stake = sum(b.stake for b in bets)
            if req_stake > balance or req_stake < self.min_stake:
                continue

            matches_bet += 1
            winning_keys = get_winning_selections(hg_arr[i], ag_arr[i], h_ht_arr[i], a_ht_arr[i])
            match_pl = 0.0

            for b in bets:
                total_bets += 1
                total_wagered += b.stake
                if b.selection in winning_keys:
                    won_bets += 1
                    profit = b.stake * (b.odds - 1.0)
                    gross_wins += profit
                    match_pl += profit
                else:
                    gross_losses += b.stake
                    match_pl -= b.stake

            balance += match_pl
            if balance > peak_balance:
                peak_balance = balance
            dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

            if record_log:
                log.append({
                    "row_idx": i,
                    "match_name": m_name,
                    "bets_placed": len(bets),
                    "match_pl": round(match_pl, 2),
                    "balance": round(balance, 2),
                })

        net_pl = balance - self.starting_balance
        roi = (net_pl / total_wagered * 100.0) if total_wagered > 0 else 0.0
        win_rate = (won_bets / total_bets * 100.0) if total_bets > 0 else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (999.0 if gross_wins > 0 else 0.0)

        return {
            "strategy": strategy.name,
            "starting_balance": self.starting_balance,
            "final_balance": round(balance, 2),
            "net_pl": round(net_pl, 2),
            "roi_pct": round(roi, 2),
            "win_rate_pct": round(win_rate, 2),
            "max_drawdown_pct": round(max_drawdown * 100.0, 2),
            "profit_factor": round(profit_factor, 2),
            "total_matches": n_matches,
            "matches_bet": matches_bet,
            "total_bets": total_bets,
            "won_bets": won_bets,
            "total_wagered": round(total_wagered, 2),
            "log": log,
        }

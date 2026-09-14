"""
engine_edge.py — Value betting strategy comparing Poisson engine probabilities to bookmaker odds.
"""
from typing import List, Dict, Any
from scipy.stats import poisson
import numpy as np
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from prediction_engine import BaseFootballStrategy, Bet


class EngineEdgeStrategy(BaseFootballStrategy):
    """
    Computes true Poisson probability distribution from fitted lambdas.
    Compares against bookmaker raw odds and fair_prob in h2h_odds.
    Places a bet if Model_Prob > Implied_Prob + edge_threshold.
    """

    def __init__(
        self,
        name: str = "EngineEdge_1X2_OU",
        edge_threshold: float = 0.03,
        stake: float = 50.0,
        max_goals: int = 8,
    ):
        super().__init__(name, {"edge_threshold": edge_threshold, "stake": stake})
        self.edge_threshold = edge_threshold
        self.stake = stake
        self.max_goals = max_goals

    def _calc_score_matrix(self, l_home: float, l_away: float) -> np.ndarray:
        goals = np.arange(self.max_goals + 1)
        p_home = poisson.pmf(goals, l_home)
        p_away = poisson.pmf(goals, l_away)
        return np.outer(p_home, p_away)

    def predict(self, match_info: Dict[str, Any], odds: Dict[str, Any]) -> List[Bet]:
        l_home = match_info.get("param_lambda_home_ft")
        l_away = match_info.get("param_lambda_away_ft")
        if not l_home or not l_away or np.isnan(l_home) or np.isnan(l_away):
            return []

        matrix = self._calc_score_matrix(l_home, l_away)
        bets = []

        # 1. 1X2 market
        p_home_win = float(np.sum(np.tril(matrix, -1)))
        p_draw = float(np.sum(np.diag(matrix)))
        p_away_win = float(np.sum(np.triu(matrix, 1)))

        m_1x2 = odds.get("1X2", {})
        candidates = [
            ("1x2_1_val", p_home_win, m_1x2.get("1x2_1_val")),
            ("1x2_x_val", p_draw, m_1x2.get("1x2_x_val")),
            ("1x2_2_val", p_away_win, m_1x2.get("1x2_2_val")),
        ]

        # 2. Total O/U 2.5
        i_indices, j_indices = np.indices(matrix.shape)
        p_over25 = float(np.sum(matrix[i_indices + j_indices > 2]))
        p_under25 = 1.0 - p_over25
        m_ou25 = odds.get("Total O/U 2.5", {})
        candidates.extend([
            ("o_u_2_5_ov_val", p_over25, m_ou25.get("o_u_2_5_ov_val")),
            ("o_u_2_5_un_val", p_under25, m_ou25.get("o_u_2_5_un_val")),
        ])

        # 3. BTTS
        p_btts = float(np.sum(matrix[1:, 1:]))
        p_nobtts = 1.0 - p_btts
        m_btts = odds.get("BTTS (GG/NG)", {})
        candidates.extend([
            ("gg_ng_gg_val", p_btts, m_btts.get("gg_ng_gg_val")),
            ("gg_ng_ng_val", p_nobtts, m_btts.get("gg_ng_ng_val")),
        ])

        for sel_key, model_p, odd_data in candidates:
            if not odd_data:
                continue
            raw_odd = odd_data.get("raw", 0.0)
            implied_p = odd_data.get("fair_prob", 0.0)
            if raw_odd <= 1.0 or implied_p <= 0.0:
                continue

            # Edge check: Model P exceeds bookmaker implied P by threshold
            edge = model_p - implied_p
            ev = (model_p * raw_odd) - 1.0
            if edge >= self.edge_threshold and ev > 0.0:
                market_name = "1X2" if "1x2" in sel_key else ("Total O/U 2.5" if "o_u" in sel_key else "BTTS")
                bets.append(Bet(market=market_name, selection=sel_key, stake=self.stake, odds=raw_odd))

        return bets

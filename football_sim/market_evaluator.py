"""
market_evaluator.py — Deterministic settlement logic for all 26 football betting markets.
"""
from typing import Set, Tuple


def get_winning_selections(hg: int, ag: int, h_ht: int, a_ht: int) -> Set[str]:
    """
    Given Full-Time (hg, ag) and Half-Time (h_ht, a_ht) scores,
    returns the set of all winning selection keys across all 26 markets.
    """
    winning = set()
    total_ft = hg + ag
    total_ht = h_ht + a_ht

    # 1X2 (FT)
    ft_res = "1" if hg > ag else ("x" if hg == ag else "2")
    winning.add(f"1x2_{ft_res}_val")

    # 1X2 (HT)
    ht_res = "1" if h_ht > a_ht else ("x" if h_ht == a_ht else "2")
    winning.add(f"ht_1x2_{ht_res}_val")

    # Double Chance
    if hg >= ag:
        winning.add("double_chance_1x_val")
    if hg != ag:
        winning.add("double_chance_12_val")
    if hg <= ag:
        winning.add("double_chance_x2_val")

    # HT/FT
    winning.add(f"ht_ft_{ht_res}_{ft_res}_val")

    # Match Totals (O/U)
    winning.add("o_u_1_5_ov_val" if total_ft > 1.5 else "o_u_1_5_un_val")
    winning.add("o_u_2_5_ov_val" if total_ft > 2.5 else "o_u_2_5_un_val")
    winning.add("o_u_3_5_ov_val" if total_ft > 3.5 else "o_u_3_5_un_val")
    winning.add("o_u_4_5_ov_val" if total_ft > 4.5 else "o_u_4_5_un_val")

    # Home Totals
    winning.add("home_o_u_0_5_ov_val" if hg > 0.5 else "home_o_u_0_5_un_val")
    winning.add("home_o_u_1_5_ov_val" if hg > 1.5 else "home_o_u_1_5_un_val")
    winning.add("home_o_u_2_5_ov_val" if hg > 2.5 else "home_o_u_2_5_un_val")
    if hg > 3.5:
        winning.add("home_o_u_3_5_ov_val")

    # Away Totals
    winning.add("away_o_u_0_5_ov_val" if ag > 0.5 else "away_o_u_0_5_un_val")
    winning.add("away_o_u_1_5_ov_val" if ag > 1.5 else "away_o_u_1_5_un_val")
    if ag > 2.5:
        winning.add("away_o_u_2_5_ov_val")
    if ag > 3.5:
        winning.add("away_o_u_3_5_ov_val")

    # Total Goals (Exact)
    tg = min(total_ft, 6)
    winning.add(f"total_goals_{tg}_val")

    # BTTS (GG/NG)
    is_btts = hg > 0 and ag > 0
    winning.add("gg_ng_gg_val" if is_btts else "gg_ng_ng_val")

    # BTTS in 1st Half
    is_btts_ht = h_ht > 0 and a_ht > 0
    winning.add("goal_goal_ht_yes_val" if is_btts_ht else "goal_goal_ht_no_val")

    # Clean Sheets
    winning.add("home_clean_sheet_yes_val" if ag == 0 else "home_clean_sheet_no_val")
    winning.add("away_clean_sheet_yes_val" if hg == 0 else "away_clean_sheet_no_val")

    # Correct Score (FT)
    winning.add(f"correct_score_{hg}_{ag}_val")

    # Correct Score (HT)
    winning.add(f"ht_correct_score_{h_ht}_{a_ht}_val")

    # Combos
    btts_str = "gg" if is_btts else "ng"
    winning.add(f"1x2_gg_{ft_res}_{btts_str}_val")

    ou15_str = "ov" if total_ft > 1.5 else "un"
    winning.add(f"1x2_o_u_1_5_{ft_res}_{ou15_str}_val")

    ou25_str = "ov" if total_ft > 2.5 else "un"
    winning.add(f"1x2_o_u_2_5_{ft_res}_{ou25_str}_val")

    return winning


def evaluate_bet(selection_key: str, multiplier: float, winning_keys: Set[str]) -> Tuple[bool, float]:
    """
    Returns (won: bool, multiplier: float).
    """
    won = selection_key in winning_keys
    return won, multiplier if won else 0.0

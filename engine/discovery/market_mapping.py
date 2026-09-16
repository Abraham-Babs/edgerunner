"""
engine/discovery/market_mapping.py
----------------------------------
Deterministic mapping from SportsExchange Virtuals sync API market IDs and selectionTypeIds
to our engine's canonical outcome keys.
"""

from typing import Dict, Tuple, Optional

# (market_id, selection_type_id) -> canonical outcome_key
MARKET_SELECTION_TO_OUTCOME: Dict[Tuple[str, str], str] = {
    # 1X2 (Market 3)
    ("3", "39"): "1x2_1_val",
    ("3", "40"): "1x2_x_val",
    ("3", "41"): "1x2_2_val",

    # Double Chance (Market 5)
    ("5", "52"): "double_chance_1x_val",
    ("5", "53"): "double_chance_12_val",
    ("5", "54"): "double_chance_x2_val",

    # Over / Under 1.5 (Market 6)
    ("6", "55"): "o_u_1_5_ov_val",
    ("6", "56"): "o_u_1_5_un_val",

    # Over / Under 2.5 (Market 7)
    ("7", "57"): "o_u_2_5_ov_val",
    ("7", "58"): "o_u_2_5_un_val",

    # Over / Under 3.5 (Market 8)
    ("8", "59"): "o_u_3_5_ov_val",
    ("8", "60"): "o_u_3_5_un_val",

    # Over / Under 4.5 (Market 35)
    ("35", "159"): "o_u_4_5_ov_val",
    ("35", "160"): "o_u_4_5_un_val",

    # Both Teams To Score / GG-NG (Market 13)
    ("13", "83"): "gg_ng_gg_val",
    ("13", "84"): "gg_ng_ng_val",
}

# Reverse lookup: outcome_key -> (market_id, selection_type_id, area_id)
OUTCOME_TO_MARKET_SELECTION: Dict[str, Tuple[str, str, str]] = {
    # Popular tab (Area 1)
    "1x2_1_val": ("3", "39", "1"),
    "1x2_x_val": ("3", "40", "1"),
    "1x2_2_val": ("3", "41", "1"),
    "double_chance_1x_val": ("5", "52", "1"),
    "double_chance_12_val": ("5", "53", "1"),
    "double_chance_x2_val": ("5", "54", "1"),
    "o_u_2_5_ov_val": ("7", "57", "1"),
    "o_u_2_5_un_val": ("7", "58", "1"),
    "gg_ng_gg_val": ("13", "83", "1"),
    "gg_ng_ng_val": ("13", "84", "1"),

    # Over / Under tab (Area 2)
    "o_u_1_5_ov_val": ("6", "55", "2"),
    "o_u_1_5_un_val": ("6", "56", "2"),
    "o_u_3_5_ov_val": ("8", "59", "2"),
    "o_u_3_5_un_val": ("8", "60", "2"),
    "o_u_4_5_ov_val": ("35", "159", "2"),
    "o_u_4_5_un_val": ("35", "160", "2"),
}

# Mapping of outcome_key to UI Tab and Category for execution fallback
OUTCOME_TO_UI_METADATA: Dict[str, Dict[str, str]] = {
    "1x2_1_val": {"category": "Popular", "tab_name": "1X2", "btn_idx": 0},
    "1x2_x_val": {"category": "Popular", "tab_name": "1X2", "btn_idx": 1},
    "1x2_2_val": {"category": "Popular", "tab_name": "1X2", "btn_idx": 2},
    "double_chance_1x_val": {"category": "Popular", "tab_name": "Double Chance", "btn_idx": 0},
    "double_chance_12_val": {"category": "Popular", "tab_name": "Double Chance", "btn_idx": 1},
    "double_chance_x2_val": {"category": "Popular", "tab_name": "Double Chance", "btn_idx": 2},
    "o_u_2_5_ov_val": {"category": "Popular", "tab_name": "O/U 2.5", "btn_idx": 0},
    "o_u_2_5_un_val": {"category": "Popular", "tab_name": "O/U 2.5", "btn_idx": 1},
    "gg_ng_gg_val": {"category": "Popular", "tab_name": "GG/NG", "btn_idx": 0},
    "gg_ng_ng_val": {"category": "Popular", "tab_name": "GG/NG", "btn_idx": 1},
    "o_u_1_5_ov_val": {"category": "Over/Under", "tab_name": "O/U 1.5", "btn_idx": 0},
    "o_u_1_5_un_val": {"category": "Over/Under", "tab_name": "O/U 1.5", "btn_idx": 1},
    "o_u_3_5_ov_val": {"category": "Over/Under", "tab_name": "O/U 3.5", "btn_idx": 0},
    "o_u_3_5_un_val": {"category": "Over/Under", "tab_name": "O/U 3.5", "btn_idx": 1},
    "o_u_4_5_ov_val": {"category": "Over/Under", "tab_name": "O/U 4.5", "btn_idx": 0},
    "o_u_4_5_un_val": {"category": "Over/Under", "tab_name": "O/U 4.5", "btn_idx": 1},
}

def map_selection_to_outcome(market_id: str, selection_type_id: str) -> Optional[str]:
    """Resolves platform market and selectionTypeId to engine outcome key."""
    return MARKET_SELECTION_TO_OUTCOME.get((str(market_id), str(selection_type_id)))

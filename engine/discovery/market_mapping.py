"""
engine/discovery/market_mapping.py
----------------------------------
Deterministic mapping from exchange virtual market IDs and selectionTypeIds
to canonical outcome keys.
"""

import os
import json
from typing import Dict, Tuple, Optional

_SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "market_schema.json")

# (market_id, selection_type_id) -> canonical outcome_key
MARKET_SELECTION_TO_OUTCOME: Dict[Tuple[str, str], str] = {}

# Reverse lookup: outcome_key -> (market_id, selection_type_id, area_id)
OUTCOME_TO_MARKET_SELECTION: Dict[str, Tuple[str, str, str]] = {}

def _init_market_mappings():
    if os.path.exists(_SCHEMA_FILE):
        try:
            with open(_SCHEMA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("mappings", []):
                    m_id = str(item["market_id"])
                    s_id = str(item["selection_type_id"])
                    a_id = str(item.get("area_id", "1"))
                    out = str(item["outcome"])
                    MARKET_SELECTION_TO_OUTCOME[(m_id, s_id)] = out
                    OUTCOME_TO_MARKET_SELECTION[out] = (m_id, s_id, a_id)
                return
        except Exception:
            pass

    # Standard fallback definitions if external schema file is not present
    fallbacks = [
        ("3", "39", "1", "1x2_1_val"), ("3", "40", "1", "1x2_x_val"), ("3", "41", "1", "1x2_2_val"),
        ("5", "52", "1", "double_chance_1x_val"), ("5", "53", "1", "double_chance_12_val"), ("5", "54", "1", "double_chance_x2_val"),
        ("6", "55", "2", "o_u_1_5_ov_val"), ("6", "56", "2", "o_u_1_5_un_val"),
        ("7", "57", "1", "o_u_2_5_ov_val"), ("7", "58", "1", "o_u_2_5_un_val"),
        ("8", "59", "2", "o_u_3_5_ov_val"), ("8", "60", "2", "o_u_3_5_un_val"),
        ("35", "159", "2", "o_u_4_5_ov_val"), ("35", "160", "2", "o_u_4_5_un_val"),
        ("13", "83", "1", "gg_ng_gg_val"), ("13", "84", "1", "gg_ng_ng_val"),
    ]
    for m, s, a, out in fallbacks:
        MARKET_SELECTION_TO_OUTCOME[(m, s)] = out
        OUTCOME_TO_MARKET_SELECTION[out] = (m, s, a)

_init_market_mappings()

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

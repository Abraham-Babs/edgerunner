"""
engine/pipeline/walkforward.py
-------------------------------
Splits historical match data chronologically, fits hit-rate edges on the
early portion only, and measures whether those edges survive on the later,
unseen portion. Nothing enters confirmed_edges.csv without passing this.
"""

import numpy as np
import pandas as pd

# Outcome column -> (market_name_in_odds_json, selection_key_in_odds_json)
OUTCOME_MARKET_MAP = {
    'H': ('1X2', '1x2_1_val'), 'D': ('1X2', '1x2_x_val'), 'A': ('1X2', '1x2_2_val'),
    '1X': ('Double Chance', 'double_chance_1x_val'),
    '12': ('Double Chance', 'double_chance_12_val'),
    'X2': ('Double Chance', 'double_chance_x2_val'),
    'O1.5': ('Total O/U 1.5', 'o_u_1_5_ov_val'), 'U1.5': ('Total O/U 1.5', 'o_u_1_5_un_val'),
    'O2.5': ('Total O/U 2.5', 'o_u_2_5_ov_val'), 'U2.5': ('Total O/U 2.5', 'o_u_2_5_un_val'),
    'O3.5': ('Total O/U 3.5', 'o_u_3_5_ov_val'), 'U3.5': ('Total O/U 3.5', 'o_u_3_5_un_val'),
    'O4.5': ('Total O/U 4.5', 'o_u_4_5_ov_val'), 'U4.5': ('Total O/U 4.5', 'o_u_4_5_un_val'),
    'GG': ('BTTS (GG/NG)', 'gg_ng_gg_val'), 'NG': ('BTTS (GG/NG)', 'gg_ng_ng_val'),
}

def add_outcome_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['H'] = (df.home_team_score > df.away_team_score).astype(int)
    df['D'] = (df.home_team_score == df.away_team_score).astype(int)
    df['A'] = (df.home_team_score < df.away_team_score).astype(int)
    df['1X'] = (df.home_team_score >= df.away_team_score).astype(int)
    df['12'] = (df.home_team_score != df.away_team_score).astype(int)
    df['X2'] = (df.home_team_score <= df.away_team_score).astype(int)
    tot = df.home_team_score + df.away_team_score
    for L in [1.5, 2.5, 3.5, 4.5]:
        df[f'O{L}'] = (tot > L).astype(int)
        df[f'U{L}'] = (tot < L).astype(int)
    df['GG'] = ((df.home_team_score > 0) & (df.away_team_score > 0)).astype(int)
    df['NG'] = 1 - df['GG']
    return df

def walkforward_edges(
    match_df: pd.DataFrame,
    odds_db: dict,
    league: str,
    split: float = 0.70,
    min_train_edge: float = 0.03,
    min_hits_train: int = 100,
    min_hits_test: int = 30,
) -> pd.DataFrame:
    """
    match_df: raw historical rows for ONE league, columns include
              id, match_name, home_team_score, away_team_score (sorted by id ascending)
    odds_db:  the loaded h2h_odds.json dict for this league (odds_db[league])
    Returns one row per (match_name, outcome) that had enough train AND test
    samples, with train_edge, test_edge, oos_t_stat, oos_roi columns.
    """
    d = add_outcome_flags(match_df.sort_values('id').reset_index(drop=True))

    rows = []
    for fx, g in d.groupby('match_name'):
        if fx not in odds_db:
            continue
        g = g.sort_values('id').reset_index(drop=True)
        n_fx = len(g)
        s_fx = int(n_fx * split)
        g_tr = g.iloc[:s_fx]
        g_te = g.iloc[s_fx:]
        if len(g_tr) < min_hits_train or len(g_te) < min_hits_test:
            continue
        for col, (mk, key) in OUTCOME_MARKET_MAP.items():
            try:
                o = odds_db[fx][mk][key]['raw']
            except (KeyError, TypeError):
                continue
            if not o:
                continue
            p_train = g_tr[col].mean()
            train_edge = p_train - 1 / o
            if train_edge < min_train_edge:
                continue
            pnl = g_te[col].values * o - 1
            test_edge = g_te[col].mean() - 1 / o
            se = pnl.std() / np.sqrt(len(pnl)) if len(pnl) > 1 else np.nan
            t_stat = pnl.mean() / se if se and se > 0 else np.nan
            rows.append({
                'league': league, 'match_name': fx, 'outcome': col, 'raw_odds': o,
                'n_train': len(g_tr), 'n_test': len(g_te),
                'train_edge': round(train_edge, 6), 'test_edge': round(test_edge, 6),
                'oos_roi': round(pnl.mean(), 6), 'oos_t_stat': round(t_stat, 3) if not np.isnan(t_stat) else None,
            })
    return pd.DataFrame(rows)

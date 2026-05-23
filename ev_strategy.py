import duckdb as db
import pandas as pd
import json
import numpy as np

with open('h2h_odds.json', 'r') as f:
    odds_data = json.load(f)['league_en']

con = db.connect()
F = "parquets/league_en.parquet"

df = con.sql(f"""
    SELECT home_team_name as home, away_team_name as away,
           home_team_score as ft_h, away_team_score as ft_a,
           home_team_halftime_score as ht_h, away_team_halftime_score as ht_a,
           (home_team_score - home_team_halftime_score) as sh_h,
           (away_team_score - away_team_halftime_score) as sh_a
    FROM '{F}'
""").df()
df['ft_total'] = df['ft_h'] + df['ft_a']

# Collect ALL +EV bets with full detail
results = []
for h2h, markets in odds_data.items():
    try:
        home, away = h2h.split(' - ')
    except: continue
    m = df[(df['home'] == home) & (df['away'] == away)]
    if len(m) == 0: continue

    def check(market_name, raw_odds, bool_series, market_type):
        if raw_odds > 0:
            tp = bool_series.mean()
            ev = tp * raw_odds - 1
            if ev > 0.03:
                results.append({
                    'H2H': h2h, 'Market': market_name, 'Type': market_type,
                    'Odds': raw_odds, 'TrueProb': tp, 'EV': ev
                })

    if '1X2' in markets:
        check("Home Win", markets['1X2'].get('1x2_1_val',{}).get('raw',0), m['ft_h']>m['ft_a'], '1X2')
        check("Draw", markets['1X2'].get('1x2_x_val',{}).get('raw',0), m['ft_h']==m['ft_a'], '1X2')
        check("Away Win", markets['1X2'].get('1x2_2_val',{}).get('raw',0), m['ft_h']<m['ft_a'], '1X2')

    if 'BTTS (GG/NG)' in markets:
        check("BTTS Yes", markets['BTTS (GG/NG)'].get('gg_ng_gg_val',{}).get('raw',0), (m['ft_h']>0)&(m['ft_a']>0), 'BTTS')
        check("BTTS No", markets['BTTS (GG/NG)'].get('gg_ng_ng_val',{}).get('raw',0), (m['ft_h']==0)|(m['ft_a']==0), 'BTTS')

    for line in ['1.5','2.5','3.5','4.5']:
        mk = f'Total O/U {line}'
        if mk in markets:
            check(f"Over {line}", markets[mk].get(f'o_u_{line.replace(".","_")}_ov_val',{}).get('raw',0), m['ft_total']>float(line), 'OU')
            check(f"Under {line}", markets[mk].get(f'o_u_{line.replace(".","_")}_un_val',{}).get('raw',0), m['ft_total']<float(line), 'OU')

    if 'Total Goals (Exact)' in markets:
        for i in range(7):
            check(f"Exact {i}", markets['Total Goals (Exact)'].get(f'total_goals_{i}_val',{}).get('raw',0), m['ft_total']==i, 'ExactGoals')

    if 'Correct Score (FT)' in markets:
        for key, val in markets['Correct Score (FT)'].items():
            parts = key.split('_')
            try:
                hg, ag = int(parts[2]), int(parts[3])
                check(f"CS {hg}-{ag}", val.get('raw',0), (m['ft_h']==hg)&(m['ft_a']==ag), 'CS')
            except: pass

    if 'Correct Score (HT)' in markets:
        for key, val in markets['Correct Score (HT)'].items():
            parts = key.split('_')
            try:
                hg, ag = int(parts[3]), int(parts[4])
                check(f"HT CS {hg}-{ag}", val.get('raw',0), (m['ht_h']==hg)&(m['ht_a']==ag), 'HTCS')
            except: pass

    if 'HT/FT' in markets:
        for key, val in markets['HT/FT'].items():
            parts = key.split('_')
            try:
                ht_r, ft_r = parts[2], parts[3]
                ht_c = (m['ht_h']>m['ht_a']) if ht_r=='1' else ((m['ht_h']==m['ht_a']) if ht_r=='x' else (m['ht_h']<m['ht_a']))
                ft_c = (m['ft_h']>m['ft_a']) if ft_r=='1' else ((m['ft_h']==m['ft_a']) if ft_r=='x' else (m['ft_h']<m['ft_a']))
                check(f"HT/FT {ht_r.upper()}/{ft_r.upper()}", val.get('raw',0), ht_c & ft_c, 'HTFT')
            except: pass

rdf = pd.DataFrame(results)

# Bankroll simulation: 1 season cycle = 380 bets (one per H2H)
# Simulate 100 season cycles betting $1 on every +EV bet
# For each tier, calculate: expected profit, variance, max drawdown

def simulate_bankroll(bets_df, n_cycles=1000, unit=1.0):
    """Simulate betting all bets in the df for n_cycles (seasons)"""
    np.random.seed(42)
    profits = []
    for _ in range(n_cycles):
        cycle_profit = 0
        for _, bet in bets_df.iterrows():
            # Simulate the outcome
            if np.random.random() < bet['TrueProb']:
                cycle_profit += unit * (bet['Odds'] - 1)  # win
            else:
                cycle_profit -= unit  # lose
        profits.append(cycle_profit)
    return np.array(profits)

# Tier definitions
tier1 = rdf[(rdf['TrueProb'] > 0.10) & (rdf['EV'] > 0.03)].copy()
tier2 = rdf[(rdf['TrueProb'] > 0.03) & (rdf['TrueProb'] <= 0.10) & (rdf['EV'] > 0.05)].copy()
tier3 = rdf[(rdf['TrueProb'] <= 0.03) & (rdf['EV'] > 0.50)].copy()

for name, tier in [("TIER 1 (Grinders)", tier1), ("TIER 2 (Sweet Spot)", tier2), ("TIER 3 (Lottery)", tier3)]:
    if len(tier) == 0: continue
    profits = simulate_bankroll(tier, n_cycles=1000)
    capital_per_cycle = len(tier) * 1.0
    
    print(f"\n=== {name} ===")
    print(f"Bets per cycle: {len(tier)}")
    print(f"Capital risked per cycle: ${capital_per_cycle:.0f}")
    print(f"Avg profit per cycle: ${profits.mean():.2f}")
    print(f"ROI per cycle: {100*profits.mean()/capital_per_cycle:.1f}%")
    print(f"Std dev: ${profits.std():.2f}")
    print(f"Worst cycle (of 1000): ${profits.min():.2f}")
    print(f"Best cycle (of 1000): ${profits.max():.2f}")
    print(f"Win rate (profitable cycles): {100*(profits>0).mean():.1f}%")
    print(f"Cycles per day: ~13")
    print(f"Expected daily profit: ${profits.mean() * 13:.2f}")
    print(f"Worst-case daily (13 bad cycles): ${profits.min() * 13:.2f}")

# Combined portfolio
combined = pd.concat([tier1, tier2])
profits = simulate_bankroll(combined, n_cycles=1000)
capital = len(combined) * 1.0
print(f"\n=== COMBINED T1+T2 (RECOMMENDED) ===")
print(f"Bets per cycle: {len(combined)}")
print(f"Capital risked per cycle: ${capital:.0f}")
print(f"Avg profit per cycle: ${profits.mean():.2f}")
print(f"ROI per cycle: {100*profits.mean()/capital:.1f}%")
print(f"Win rate (profitable cycles): {100*(profits>0).mean():.1f}%")
print(f"Expected daily profit (13 cycles): ${profits.mean() * 13:.2f}")
print(f"Worst-case daily: ${profits.min() * 13:.2f}")

# Market type breakdown
print(f"\n=== BREAKDOWN BY MARKET TYPE ===")
for mtype in rdf['Type'].unique():
    sub = rdf[rdf['Type'] == mtype]
    print(f"{mtype}: {len(sub)} bets, avg EV={100*sub['EV'].mean():.1f}%, avg TrueProb={100*sub['TrueProb'].mean():.1f}%")

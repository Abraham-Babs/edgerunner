# PROJECT CONTEXT & HANDOVER: EXCHANGE VIRTUAL VALUE BETTING ENGINE

> **⚠️ LLM Collaborators: ALWAYS use `git` before and after making changes. Branch, commit, review diffs. Read the actual source code — not just docs or comments — before modifying anything. Verify your changes with `--dry-run` before going live.**

## 1. Platform & Leagues
* **Platform**: SportsExchange Nigeria Scheduled Virtual Football.
* **Leagues (4)**:
  * **Premier League (England - league_en)**: 20 teams, 10 matches/round, 180s cycle.
  * **Primera Liga (Spain - league_es)**: 20 teams, 10 matches/round, 180s cycle.
  * **Serie League (Italy - league_it)**: 20 teams, 10 matches/round, 180s cycle.
  * **Bundes League (Germany - league_de)**: 18 teams, 9 matches/round, 90s cycle.
* **Active Profile**: `ultra_conservative`.

---

## 2. Edge Pipeline

### Edge Compilation (`engine/pipeline/edge_compiler.py`)
- Ingests match parquets + `h2h_odds.json`.
- Fits empirical hit rates per matchup/outcome.
- **MIN_HITS = 100** (minimum observations to qualify).

### Walk-Forward Validation (`engine/pipeline/walkforward.py`)
- Per-matchup 70/30 chronological split. Each fixture's own historical observations are split chronologically so newly introduced teams get evaluated rather than dropped by global date cutoffs.
- OOS portion measures real forward performance.
- **Gate**: Only edges with `oos_t_stat >= 2.0` pass into `confirmed_edges.csv`.
- Each confirmed edge carries: `min_edge`, `oos_roi`, `oos_t_stat`, `n_train`.

### Per-League Odds Bands (`config.py` → `PROFILES`)
- Each league has its own `min_odds` and `max_odds`, calibrated via `engine/pipeline/band_sweep.py`.
- Example (ultra_conservative):
  * league_en (England): 2.00 – 3.20
  * league_de (Germany): 1.50 – 5.00
  * league_es (Spain): 1.45 – 3.50
  * league_it (Italy): 1.45 – 3.50

---

## 3. Edge Matching (Runtime)

`EdgeMatcher` (`engine/edge_matcher.py`) loads `confirmed_edges.csv` at startup and builds a lookup keyed by `(league, match_name, outcome)`.

**Filters applied per profile**:
- `min_edge` threshold.
- Per-league `min_odds` / `max_odds` bands.

**No win-rate filter exists.** Selection is purely edge + odds band.

Auto-reloads when `h2h_odds.json` changes (triggers recompilation).

---

## 4. Conviction Tiers & Stake Sizing

### Tier Classification (`ticket_builder.py → classify_tier`)
Based on **edge and odds only**:

| Tier | Edge | Max Odds |
|------|------|----------|
| 1 (Anchor) | ≥ 6% | ≤ 2.40 |
| 2 (Value) | ≥ 5% | ≤ 3.20 |
| 3 (Speculative) | Below above | Any |

### Stake Sizing (`ticket_builder.py → calculate_tier_stake`)

| Type | Base Rate | Scaled Up To | Scaling Driver |
|------|-----------|-------------|----------------|
| Tier 1 Single | 4.0% | 5.5% | `edge - 0.06` |
| Tier 2 Single | 2.5% | 3.5% | `edge - 0.04` |
| Tier 3 Single | 2.0% | 2.0% (flat) | — |
| Double | 2.5% | 3.5% | `edge - 0.06` |
| Treble | ₦10 flat | ₦10 flat | — |

**Confidence Scaling**: `min(1.0, n_train / 300)` — stakes are proportionally reduced for edges with fewer than 300 training observations.

**OOS Edge Sizing**: `runner.py` propagates `oos_edge` to candidates. Kelly fraction uses OOS edge, not raw in-sample edge.

**Human Steps**: All stakes snap to `₦10, ₦15, ₦20 ... ₦500`.

---

## 5. Risk Management (`runner.py → RiskManager`)

### Portfolio Modes (by True Equity = Cash + In-Play Stakes)

| Equity | Mode | Max Tickets | Doubles | Trebles |
|--------|------|-------------|---------|---------|
| < ₦1,200 | BEDROCK_SHIELD | 2 | Yes (≤2.80 odds) | No |
| ₦1,200 – ₦5,999 | CORE_GROWTH | 2 | Yes (≤3.00 odds) | No |
| ≥ ₦6,000 | EXPANSION_RATCHET | 3 | Yes (≤3.50 odds) | Yes |

### Circuit Breakers
- **25% Drawdown**: Dynamic monitoring polls balance every 25s; resumes on recovery.
- **Hard Floor**: ₦100 or 50% session loss → engine terminates.
- **7 Consecutive Losses**: 12-minute cool-off pause.
- **Match Dedup**: Exposure keyed by `"{league} | {match_name}"` — no duplicate exposure.
- **Max Concurrent**: 10 active pending bets across all leagues.

---

## 6. Bet Execution & Logging (`engine/bettor.py`)

### DOM Validation (3-Point)
- Badge count assertion after odds tap.
- Stake input echo verification before Place Bet.
- Pre-click odds parity ±0.02.

### Settlement Logging
- Logs to `analysis/results/bet_log.csv`.
- Fields: `bet_id`, `outcome`, `returned_amount`, `code_version`, plus standard ticket fields.
- Settlement reconciliation runs each engine cycle.

---

## 7. Critical Engineering Fixes (DO NOT REVERT)
1. **Betslip drawer close**: `button[data-testid="betslip-header-title-close-icon"]` + `(332, 84)` + Escape fallback.
2. **Post-tap badge assertion**: Retries tap if badge stays at 0.
3. **Stake echo assertion**: Auto-clears and retypes on mismatch.
4. **Relaxed countdown**: True 0s boundary (`slip_sec <= 0`).
5. **No candidate blacklisting**: Engine self-corrects modal state instead of dropping candidates.
6. **Network route aborts**: `*free2play*`, `*premier-game*`, `*exchange-core-account*` blocked at network level.
7. **Stateful market assertion**: Checks `selected-market-name` before odds clicks.
8. **Vertical week bounding**: Fixtures bounded between `<p>Week X</p>` headers.
9. **Mobile tab auto-scroll**: Off-screen sub-tabs scrolled into view automatically.

---

## 8. Startup

```bash
# Live
.venv\Scripts\python -u engine/runner.py --profile ultra_conservative

# Dry-run
.venv\Scripts\python -u engine/runner.py --profile ultra_conservative --dry-run

# Limited rounds
.venv\Scripts\python -u engine/runner.py --profile ultra_conservative --max-rounds 5
```

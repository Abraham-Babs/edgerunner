# SportsExchange Virtual Leagues — Autonomous Value Betting Engine

An autonomous betting system that identifies and exploits statistical edges in SportsExchange's virtual football leagues. It runs continuously, cycles through four leagues, reads live odds directly off the screen, cross-checks them against a walk-forward validated edge model, and places only bets where the numbers are genuinely in our favour.

> **⚠️ LLM Collaborators: ALWAYS use `git` before and after making changes. Branch, commit, and never force-push to main. Read the actual code — not just docs or comments — before modifying anything.**

---

## How It Works

### 1. Edge Pipeline (Offline)
Historical match data for each league is processed through a multi-stage pipeline:

1. **Edge Compiler** (`engine/pipeline/edge_compiler.py`): Fits empirical hit rates against bookmaker odds across all matchups/outcomes. Minimum sample size: **100 observations** (`MIN_HITS`).
2. **Walk-Forward Validator** (`engine/pipeline/walkforward.py`): Splits data chronologically 70/30. Edges must demonstrate positive OOS ROI with `oos_t_stat >= 2.0` to be confirmed. This prevents in-sample overfitting from reaching production.
3. **Output**: `analysis/results/confirmed_edges.csv` — each row carries `min_edge`, `oos_roi`, `oos_t_stat`, and `n_train` metadata.

### 2. High-Speed HTTP/2 Discovery
Instead of slow, fragile browser page scraping across 4 leagues, the engine polls SportsExchange's raw virtuals endpoints concurrently via unauthenticated HTTP/2 in ~1.5 seconds (`engine/discovery/client.py`). It syncs server clock skew and continuously updates the active candidate pool, immediately evicting concluded rounds.

### 3. Per-League Odds Bands
Each league has independently calibrated `min_odds` / `max_odds` in `config.py`, derived from odds-band sweeps (`engine/pipeline/band_sweep.py`). This excludes negative-EV zones that differ by league.

### 4. Conviction Tiers & OOS-Scaled Kelly Sizing
Qualifying selections are graded into tiers based on **edge magnitude and odds only** (no win-rate filter):

| Tier | Name | Edge | Max Odds | Stake Sizing |
|------|------|------|----------|--------------|
| 1 | Anchor | ≥ 6% | ≤ 2.40 | 4.0% → 5.5% of bankroll, scaled by edge |
| 2 | Value | ≥ 5% | ≤ 3.20 | 2.5% → 3.5% of bankroll, scaled by edge |
| 3 | Speculative | Any confirmed | > 3.20 | 2.0% flat |
| Double | Smart Double | Combined | ≤ 3.00 | 2.5% → 3.5% |
| Treble | Micro-Treble | Cross-league | ≤ 4.20 | ₦10 platform minimum |

**Confidence Scaling**: All stakes are multiplied by `min(1.0, n_train / 300)`, down-weighting edges with thin sample sizes.

**OOS Edge Sizing**: Kelly fraction uses the out-of-sample edge (`oos_edge`), not the in-sample `min_edge`, for stake calculation.

Stakes snap to human increments (`₦10, ₦15, ₦20 ... ₦500`).

### 5. Unified Rolling Master Board
The engine maintains an in-memory sliding window across all 4 leagues:
- Retains active rounds (Weeks 1–4), only scraping newly unlocked rounds.
- Cross-league doubles combine independent selections from different leagues.
- Micro-trebles combine 3 anchor legs across 3 distinct leagues.
- Candidates sorted by **Tier → Edge descending**.

### 6. Two-Layer Execution & Adaptive EDF Scheduler
- **Earliest Deadline First (EDF) Scheduling**: Sorts tickets strictly by kickoff urgency ($D_1 \le D_2 \dots$).
- **Adaptive Equal-Slack Pacing**: Distributes available idle time evenly across bets (10s–25s target) with natural human fast-follow bursts (5.0s–7.5s).
- **Surplus Ticket Preservation**: Tickets exceeding the concurrent risk cap are retained on the MasterBoard across cycles rather than discarded.
- **Layer 1 (Camouflage Decoy)**: Generates human interaction telemetry ahead of submission (bypassed if $<4.0$s to kickoff).
- **Layer 2 (In-Session API Dispatch)**: Deterministic, sub-second submission via authenticated browser fetch directly to SportsExchange's scheduled virtuals endpoint.
- **Post-Submission State Purge**: Programmatically clears betslip localStorage keys and drawer state to keep DOM pristine.

### 7. Risk Management (Pure Mathematical Model)
True Equity = `Live Cash + In-Play Stakes`.
In an independent RNG process (i.i.d.), each round is memoryless. The system relies strictly on capital preservation:

| Equity | Mode | Max Tickets/Cycle | Notes |
|--------|------|-------------------|-------|
| < ₦1,200 | BEDROCK_SHIELD | 2 | No trebles, max 4 concurrent bets, ~85% bankroll protected in cash |
| ₦1,200 – ₦5,999 | CORE_GROWTH | 2 | No trebles, max 4 concurrent bets |
| ≥ ₦6,000 | EXPANSION_RATCHET | 3 | Trebles + satellite plays enabled |

- **Fractional Staking**: Sized at 3%–4% per bet, capping total live exposure to ~15% of bankroll.
- **Hard Floor**: Automatic immediate shutdown if equity drops below ₦100 or 50% of initial deposit.
- **No Gambler's Fallacy**: Zero artificial streak cool-offs or profit breathers that interrupt positive-EV compounding.
- **Match-Level Dedup**: Exposure keyed by `"{league} | {match_name}"` — no duplicate exposure.

### 8. Automated Settlement Logging
Bet outcomes are logged to `analysis/results/bet_log.csv` with `bet_id`, `outcome` (`WON`/`LOST`), `returned_amount`, and `receipt_file` (coupon code). The engine queries SportsExchange's `/my-bets/virtuals/settled` endpoint via in-session API at startup and cycle boundaries to automatically reconcile outcomes without interrupting the live board.

---

## Running the Engine

```bash
# Live autonomous engine
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative

# Dry-run (stages live odds, verifies betslip & stake, zero real money)
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative --dry-run

# Limit to N cycles
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative --dry-run --max-rounds 5
```

---

## Project Structure

```
engine/
  runner.py              — Orchestrator. Main loop, risk management, portfolio modes.
  master_board.py        — In-memory sliding window cache for all leagues/rounds.
  ticket_builder.py      — Assembles singles, doubles, trebles with Kelly sizing.
  bettor.py              — Executes tickets on SportsExchange mobile UI with touch dispatch.
  discovery/             — HTTP/2 concurrent odds discovery and clock skew sync.
  parser.py              — DOM cleanup, preloader removal, tab selection.
  edge_matcher.py        — Loads confirmed edges, validates live odds against them.
  human_interaction.py   — Spatial jitter, natural pauses, mobile touch simulation.
  config.py              — Profiles, per-league odds bands, capital thresholds.
```

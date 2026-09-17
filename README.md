# Autonomous Quantitative Execution & Value Trading Engine

An institutional-grade algorithmic sports trading system designed for low-latency market discovery, statistical edge exploitation, dynamic Earliest Deadline First (EDF) order execution, and non-ergodic portfolio risk management.

---

## System Architecture

The engine implements a decoupled two-tier architecture separating high-speed market discovery from deterministic session order dispatch:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. HIGH-SPEED HTTP/2 DISCOVERY (engine/discovery/client.py) │
│    - Concurrent market polling across leagues in ~1.5s       │
│    - Server clock skew synchronization via HTTP Date header │
│    - Dynamic odds validation against bivariate Poisson model│
│    - Caches qualified +EV edges into MasterBoard memory pool│
└──────────────────────────────┬──────────────────────────────┘
                               │ (Triggered when qualified edges exist)
┌──────────────────────────────▼──────────────────────────────┐
│ 2. TWO-LAYER ADAPTIVE DISPATCH (engine/bettor.py)           │
│    - Layer 1: Human interaction telemetry & spatial jitter  │
│    - Layer 2: In-session authenticated API dispatch (<100ms)│
│    - Post-Dispatch: Programmatic DOM & storage state purge  │
│    - Reconciliation: In-session settled order reconciliation│
└─────────────────────────────────────────────────────────────┘
```

---

## Core Engineering Highlights

### 1. Offline Quantitative Pipeline & Walk-Forward Validation
To eliminate in-sample backtest overfitting:
* **Edge Compiler** (`engine/pipeline/edge_compiler.py`): Estimates empirical probability distributions across matchup parameter spaces ($N \ge 100$).
* **Walk-Forward Validator** (`engine/pipeline/walkforward.py`): Performs chronological 70/30 train/test splits. Edges are rejected unless out-of-sample ROI demonstrates statistical significance with student's $t \ge 2.0$.
* **Poisson Lambda Fitting**: Real-time cross-checking of 1X2, Double Chance, and Totals against bivariate Poisson distributions.

### 2. Low-Latency HTTP/2 Market Discovery
* Utilizes multiplexed HTTP/2 streams over persistent TLS connections to poll multi-league candidate pools in sub-2 seconds.
* Implements millisecond-level server clock skew synchronization (`sync_clock_skew`) to ensure deterministic countdowns to market close.

### 3. Conviction Tiers & Out-of-Sample Kelly Sizing
Positions are sized dynamically using out-of-sample edge calibration:
* **Tier 1 (Anchor)**: Edge $\ge 6\%$, Odds $\le 2.40$ $\rightarrow$ Base stake 4.0%–5.5% of bankroll.
* **Tier 2 (Value)**: Edge $\ge 5\%$, Odds $\le 3.20$ $\rightarrow$ Base stake 2.5%–3.5% of bankroll.
* **Tier 3 (Speculative)**: Any confirmed edge $\rightarrow$ 2.0% flat.
* **Sample Size Attenuation**: Kelly fraction is dampened by sample density: $\text{scale} = \min(1.0, N_{\text{train}} / 300)$.

### 4. Earliest Deadline First (EDF) Adaptive Execution
* **Deadline Priority**: Sorts pending orders by event kickoff urgency ($D_1 \le D_2 \dots$).
* **Equal-Slack Pacing**: Calculates available slack before event lock and distributes spacing evenly (10s–25s target with fast-follow bursts).
* **Surplus Preservation**: Retains excess positive-EV candidates across execution cycles without dropping valid edges.

### 5. Quantitative Capital Shields & Risk Controls
Virtual sports markets are memoryless i.i.d. stochastic processes. The engine rejects gamblers' fallacy heuristics in favor of strict capital preservation:

| Equity Tier | Mode | Max Orders/Cycle | Exposure Limits |
|---|---|---|---|
| `< 1,200 units` | **BEDROCK_SHIELD** | 2 | Max 4 active orders (~15% bankroll, ~85% liquid cash shield) |
| `1,200 – 5,999 units` | **CORE_GROWTH** | 2 | Max 4 active orders |
| `≥ 6,000 units` | **EXPANSION_RATCHET**| 3 | Max 10 active orders |

* **Match Deduplication**: Guarantees zero conflicting or correlated exposure on the same event.
* **Hard Stop-Loss Floor**: Immediate automated termination if true equity drops below 50% of starting capital.

---

## Repository Structure

```
engine/
  runner.py              — Execution orchestrator, event loop, and capital risk controls.
  master_board.py        — In-memory rolling window cache across leagues and rounds.
  ticket_builder.py      — Multi-leg ticket assembler with fractional Kelly sizing.
  bettor.py              — Order execution engine, session API dispatch, and UI driver.
  discovery/             — High-concurrency HTTP/2 market polling & clock skew sync.
  parser.py              — DOM parser, overlay purger, and fixture extractor.
  edge_matcher.py        — Live odds validation against pre-compiled edge tables.
  human_interaction.py   — Natural Bezier interaction curves and timing jitter.
  config.py              — League parameters, odds bands, and exchange endpoints.
analysis/
  results/               — Confirmed edges, walk-forward stats, and order logs.
```

---

## Quickstart & Verification

### 1. Environment Configuration
Copy the example environment configuration:
```bash
cp .env.example .env
```

### 2. Dry-Run Simulation (0 Financial Risk)
Verify DOM interaction, payload serialization, and odds validation without placing real orders:
```bash
python -m engine.runner --profile ultra_conservative --dry-run --max-rounds 1
```

### 3. Full Integration Suite
Run the end-to-end dry-fire verification suite:
```bash
python test_dry_fire_suite.py
```

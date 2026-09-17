# Project Context & Engineering Notes

This document captures the architectural decisions, math model, execution pipeline, and production gotchas learned while building and running this trading engine.

---

## 1. Platform & Leagues

The engine targets high-frequency virtual sports leagues running on fixed round intervals:

* **Virtual Premier League (England - `league_en`)**: 20 teams, 10 matches per round, 180-second cycle.
* **Virtual Primera Liga (Spain - `league_es`)**: 20 teams, 10 matches per round, 180-second cycle.
* **Virtual Serie League (Italy - `league_it`)**: 20 teams, 10 matches per round, 180-second cycle.
* **Virtual Bundes League (Germany - `league_de`)**: 18 teams, 9 matches per round, 90-second cycle.

Default operating profile: `ultra_conservative`.

---

## 2. Architecture: Discovery + Two-Layer Execution

The engine uses a two-tier architecture separating market monitoring from order execution:

1. **High-Speed HTTP/2 Discovery (`engine/discovery/client.py`)**:
   * Scans all 4 leagues concurrently in ~1.5 seconds.
   * Calibrates local clock skew against the exchange server using HTTP Date headers.
   * Matches live odds against bivariate Poisson lambda models.
   * Stores qualifying positive expected-value (+EV) bets in a shared MasterBoard cache.

2. **Two-Layer Execution (`engine/bettor.py`)**:
   * **Telemetry Layer**: Dispatches natural touch and scroll events ahead of order submission to satisfy bot-detection checks.
   * **Direct Session Dispatch**: Sends the authenticated betting payload directly through the active browser session for sub-second execution.
   * **State Cleanup**: Automatically purges DOM betslip elements and storage state between orders.
   * **Settlement Reconciliation**: Polls settled bet endpoints in the background and writes outcomes (WON/LOST) and returns directly to `bet_log.csv`.

---

## 3. Statistical Model & Edge Gate

### Edge Computation & Validation
* Live odds across 1X2, Double Chance, and Over/Under markets are compared against pre-computed bivariate Poisson models (`lookup/matchup_lambdas_league_*.parquet`).
* Expected Value formula: `EV = (Model Probability * Live Odds) - 1.0`.
* The `ultra_conservative` profile requires at least a 5% positive edge (`EV >= 0.05`).

### Calibrated Odds Bands
Odds outside these boundaries are discarded to avoid high-vig traps or erratic longshots:
* England (`league_en`): 2.00 to 3.20
* Germany (`league_de`): 1.50 to 5.00
* Spain (`league_es`): 1.45 to 3.50
* Italy (`league_it`): 1.45 to 3.50

---

## 4. Conviction Tiers & Staking

### Tier Classification (`engine/ticket_builder.py`)
* **Tier 1 (Anchor)**: EV >= 6% and odds <= 2.40. Base stake is 4.0% of bankroll.
* **Tier 2 (Value)**: EV >= 5% and odds <= 3.20. Base stake is 2.5% to 3.5% of bankroll.
* **Tier 3 (Speculative)**: Any remaining qualifying edge. Staked at 2.0% flat.
* **Smart Doubles**: Combined odds capped at 2.80 to 3.00.
* **Human Step Quantization**: All stakes round to natural human numbers (e.g., 10, 15, 20, 25 ... 500).

---

## 5. Bankroll Risk Management (`RiskManager`)

Virtual sports rounds are memoryless, independent random number generator (RNG) events. The engine avoids gambler's fallacy logic (like streak cool-downs or Martingale doubling) and relies entirely on strict bankroll rules:

* **Cash Shield**: With fractional 3% to 4% stakes and a 4-ticket cap, roughly 85% of total bankroll remains liquid and protected against simultaneous drawdowns.
* **Hard Stop-Loss Floor**: If account equity drops below 50% of starting capital or under the critical floor, the engine aborts immediately.
* **Failure Circuit Breaker**: If 3 order submissions fail consecutively, recovery self-healing runs. If 6 fail in a row, the engine shuts down to avoid runaway errors if the UI changes.

---

## 6. Key Production Lessons & Gotchas

1. **Native Mobile Touch Events**:
   Because mobile viewports are simulated with touch enabled, standard desktop mouse clicks often fail to trigger odds buttons. The code uses `element.tap()` with a force-click fallback.

2. **Preloader Overlays**:
   Platforms often inject high z-index loading screens that intercept pointer events. `parser.clean_page(page)` removes these elements before interacting with odds buttons.

3. **Ad Tracker Route Blocking**:
   Third-party ad pixels and trackers often cause navigation timeouts on slow connections. Network routing explicitly blocks known tracking domains to maintain low latency.

4. **Static Virtual Odds**:
   Unlike live human sports where odds float constantly, virtual sports odds are fixed once generated for that round. Once parsed, they do not drift prior to kickoff.

5. **Earliest Deadline First (EDF) Pacing**:
   Tickets are sorted by kickoff time so urgent matches are placed first. Spacing is dynamically paced (typically 10 to 25 seconds between orders) to mimic human behavior.

6. **Dry-Run Mode**:
   Running with `--dry-run` performs all odds parsing, validation, ticket building, and betslip population, but halts before final submission, captures a screenshot, and clears the slip.

---

## 7. How to Run

From the project root:

```bash
# 1. Run offline paper-trading simulation (0 credentials or browser needed)
python -m engine.runner --mock --max-rounds 2

# 2. Run unit tests
python -m engine.tests.test_tickets

# 3. Run safe live dry-run (populates UI, saves screenshots, places 0 real bets)
python -m engine.runner --profile ultra_conservative --dry-run --max-rounds 1
```

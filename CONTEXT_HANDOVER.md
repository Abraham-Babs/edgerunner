# PROJECT CONTEXT & HANDOVER: QUANTITATIVE SPORTS TRADING ENGINE

> **⚠️ ALL COLLABORATORS & AGENTS:**
> 1. ALWAYS use `git` before and after modifying files. Review diffs with `git diff`.
> 2. Read the actual source code — do NOT make assumptions or rely on stale mental models.
> 3. Verify changes with `--dry-run` before attempting real money betting.
> 4. Keep code minimal and clean. No artificial sleeps or Gambler's Fallacy bloat.

---

## 1. Platform & Leagues
* **Platform**: Virtual Sports Execution Exchange (`EXCHANGE_BASE_URL`).
* **Leagues (4 Active)**:
  * **Virtual Premier League (England - `league_en`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Virtual Primera Liga (Spain - `league_es`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Virtual Serie League (Italy - `league_it`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Virtual Bundes League (Germany - `league_de`)**: 18 teams, 9 matches/round, 90s cycle.
* **Default Active Profile**: `ultra_conservative`.

---

## 2. Architecture: Decoupled Discovery + Two-Layer Session Execution

The engine operates on a clean two-tier architecture:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. HIGH-SPEED HTTP/2 DISCOVERY (engine/discovery/client.py) │
│    - Scans all 4 leagues concurrently in ~1.5s via HTTP/2   │
│    - Syncs server clock skew via HTTP Date header           │
│    - Matches odds against Poisson bivariate lambda models   │
│    - Caches qualified +EV edges in MasterBoard memory pool  │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Only if qualified tickets exist)
┌──────────────────────────────▼──────────────────────────────┐
│ 2. TWO-LAYER PLAYWRIGHT EXECUTION (engine/bettor.py)        │
│    - Layer 1 (Camouflage): Sends authentic human UI         │
│      telemetry ahead of dispatch (<4.0s emergency bypass)   │
│    - Layer 2 (Dispatch): In-session authenticated API POST  │
│      to dispatch endpoint (sub-second)                      │
│    - Post-Dispatch: Programmatic localStorage & drawer wipe │
│    - Settlement: In-session API queries to settled orders   │
│      reconciles WON/LOST and payout directly into log.csv   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Statistical Edge Pipeline & Math Model

### Edge Computation & Poisson Validation
- Live odds across 1X2, Double Chance, and Over/Under are cross-checked against bivariate Poisson models (`matchup_lambdas_league_*.parquet`).
- Expected Value: $\text{EV} = (\text{Model Probability} \times \text{Live Odds}) - 1$.
- `ultra_conservative` requires $\text{EV} \ge +5\%$ statistical advantage.

### Per-League Calibrated Odds Bands (`engine/config.py`)
Odds outside these boundaries are rejected to avoid low-liquidity or heavily raked market traps:
- `league_en` (England): `2.00 – 3.20`
- `league_de` (Germany): `1.50 – 5.00`
- `league_es` (Spain): `1.45 – 3.50`
- `league_it` (Italy): `1.45 – 3.50`

---

## 4. Conviction Tiers & Stake Sizing

### Tier Classification (`engine/ticket_builder.py`)
- **Tier 1 (Anchor)**: $\text{EV} \ge 6\%$, Odds $\le 2.40$ → Base stake 4.0% of bankroll.
- **Tier 2 (Value)**: $\text{EV} \ge 5\%$, Odds $\le 3.20$ → Base stake 2.5%–3.5% of bankroll.
- **Tier 3 (Speculative)**: Any confirmed edge → 2.0% flat.
- **Smart Doubles**: Combined odds $\le 2.80$–$3.00$ → 2.5%–3.5% stake.
- **Human Increments**: Stakes snap cleanly to steps: `10, 15, 20, 25 ... 500`.

---

## 5. Risk Management (`engine/runner.py → RiskManager`)

Virtual sports is an independent, memoryless RNG process (i.i.d.).
**Gambler's Fallacy heuristics (streak cool-offs, artificial loss pauses, profit breathers) have been permanently purged.**

The system relies strictly on quantitative capital controls:

| Equity (`Live Cash + In-Play`) | Mode | Max Tickets/Cycle | Max In-Play Exposure |
|---|---|---|---|
| `< 1,200 units` | **BEDROCK_SHIELD** | 2 | Max 4 active tickets (~14% total bankroll) |
| `1,200 – 5,999 units` | **CORE_GROWTH** | 2 | Max 4 active tickets |
| `≥ 6,000 units` | **EXPANSION_RATCHET**| 3 | Max 10 active tickets (satellites enabled) |

### Non-Negotiable Capital Shields:
1. **~85% Bankroll Cash Shield**: Per-bet staking (3%–4%) combined with the 4-ticket cap guarantees ~85% of capital remains liquid and protected from simultaneous loss.
2. **Hard Stop-Loss Floor**: If True Equity breaches `< 100 units` or drops `50%` below starting capital, the engine triggers a hard emergency termination.
3. **Consecutive Failure Alert**: If 3 bet submission attempts fail consecutively, self-healing triggers; if 6 fail, the engine aborts to protect against interface redesigns.

---

## 6. Critical Engineering Gotchas & Invariants (DO NOT REVERT)

1. **Native Mobile Touch Dispatch (`element.tap()`):**
   Mobile web apps operate with `has_touch=True`. Standard desktop `page.mouse.click()` or `click(force=True)` **will NOT trigger odds selections**. Always use `element.tap()` (with fallback to `click(force=True)`).
2. **Preloader Overlay (`z-[99999999]`):**
   Platforms frequently inject preloader overlays covering the screen. `parser.clean_page(page)` removes this overlay. Always run `clean_page()` before UI interactions.
3. **Analytics & Ad Tracker Route Aborting:**
   External ad tracking pixels cause navigation timeouts on slower networks. [runner.py](file:///engine/runner.py) aborts `google-analytics`, `doubleclick`, `facebook`, `bing`, and related tracking requests.
4. **Phone Login Format:**
   `.env` `EXCHANGE_USERNAME` formatted for target mask. If provided with a leading `0`, [bettor.py](file:///engine/bettor.py) strips the leading zero automatically.
5. **Betslip Drawer Scoping:**
   Do not query generic `div[class*="drawer"]`—scope to `[data-testid="betslip-header"]` and its parent tree.
6. **Unified `--dry-run` and `dry_fire` Flag:**
   `bettor.execute_ticket()` checks `if dry_fire or dry_run:` to ensure that `--dry-run` halts before the final "PLACE BET" tap, saves screenshot proof, and clears the slip without deducting money.
7. **In-Session Settled Bets API Reconciliation:**
   Settled bets are queried via the in-session authenticated route (`EXCHANGE_SETTLED_URL`).
   The engine updates `outcome` (`WON`/`LOST`), `settled_at`, and `returned_amount` in `analysis/results/bet_log.csv` without page navigation or board disturbance.
8. **Virtual Odds Do NOT Drift / Shift Dynamically:**
   Virtual sports odds are static algorithmic constants determined by the RNG model per matchup—they do not float or drift like real sports markets.
9. **Earliest Deadline First (EDF) Equal-Slack Adaptive Scheduler:**
   Tickets are sorted by kickoff urgency ($D_1 \le D_2 \dots$). Adaptive pacing dynamically distributes slack (10s–25s target) with occasional fast-follow bursts (5.0s–7.5s). Surplus tickets are retained on the MasterBoard across cycles rather than dropped.
10. **Zero-Locking Submissions:**
    Exchanges accept tickets down to the millisecond before event kickoff. Any HTTP 400 with `EVENT_EXPIRED` indicates submission occurred after kickoff epoch. Payload submission is deterministic and instant via direct session fetch.

---

## 7. How to Run the Engine

Always activate virtual environment first:
```powershell
# 1. Run live dry-fire test (0 real money, captures UI screenshot evidence)
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative --dry-run --max-rounds 1

# 2. Run continuous live autonomous execution
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative

# 3. Fast unauthenticated HTTP discovery diagnostics
.venv\Scripts\python scratch/test_discovery_client.py
```

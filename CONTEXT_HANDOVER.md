# PROJECT CONTEXT & HANDOVER: EXCHANGE VIRTUAL VALUE BETTING ENGINE

> **⚠️ ALL COLLABORATORS & AGENTS:**
> 1. ALWAYS use `git` before and after modifying files. Review diffs with `git diff`.
> 2. Read the actual source code — do NOT make assumptions or rely on stale mental models.
> 3. Verify changes with `--dry-run` before attempting real money betting.
> 4. Keep code minimal and clean. No artificial sleeps or Gambler's Fallacy bloat.

---

## 1. Platform & Leagues
* **Platform**: SportsExchange Nigeria Scheduled Virtual Football (`sports-exchange.internal`).
* **Leagues (4 Active)**:
  * **Premier League (England - `league_en`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Primera Liga (Spain - `league_es`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Serie League (Italy - `league_it`)**: 20 teams, 10 matches/round, 180s cycle.
  * **Bundes League (Germany - `league_de`)**: 18 teams, 9 matches/round, 90s cycle.
* **Default Active Profile**: `ultra_conservative`.

---

## 2. Architecture: Decoupled Discovery + Targeted Browser Execution

The engine operates on a clean two-tier architecture:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. HIGH-SPEED HTTP/2 DISCOVERY (engine/discovery/client.py) │
│    - Scans all 4 leagues concurrently in ~1.5s via HTTP/2   │
│    - Syncs SportsExchange server clock skew via HTTP Date header   │
│    - Matches odds against Poisson bivariate lambda models    │
│    - Caches qualified +EV edges in MasterBoard memory pool  │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Only if qualified tickets exist)
┌──────────────────────────────▼──────────────────────────────┐
│ 2. TARGETED PLAYWRIGHT EXECUTION (engine/bettor.py)         │
│    - Launches headless Chromium disguised as Itel A6611L    │
│    - Native mobile touch dispatch: element.tap() + jitter   │
│    - Preloader & modal overlay purger (parser.clean_page)   │
│    - In-betslip 4-point assertion & stake echo validation   │
│    - Intercepts and captures screenshot evidence in dry-run │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Statistical Edge Pipeline & Math Model

### Edge Computation & Poisson Validation
- Live odds across 1X2, Double Chance, and Over/Under are cross-checked against bivariate Poisson models (`matchup_lambdas_cat_*.parquet`).
- Expected Value: $\text{EV} = (\text{Model Probability} \times \text{Live Odds}) - 1$.
- `ultra_conservative` requires $\text{EV} \ge +5\%$ statistical advantage.

### Per-League Calibrated Odds Bands (`engine/config.py`)
Odds outside these boundaries are rejected to avoid low-liquidity or heavily raked bookmaker traps:
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
- **Human Increments**: Stakes snap cleanly to steps: `₦10, ₦15, ₦20, ₦25 ... ₦500`.

---

## 5. Risk Management (`engine/runner.py → RiskManager`)

Virtual football is an independent, memoryless RNG process (i.i.d.).
**Gambler's Fallacy heuristics (streak cool-offs, artificial loss pauses, profit breathers) have been permanently purged.**

The system relies strictly on quantitative capital controls:

| Equity (`Live Cash + In-Play`) | Mode | Max Tickets/Cycle | Max In-Play Exposure |
|---|---|---|---|
| `< ₦1,200` | **BEDROCK_SHIELD** | 2 | Max 4 active tickets (~14% total bankroll) |
| `₦1,200 – ₦5,999` | **CORE_GROWTH** | 2 | Max 4 active tickets |
| `≥ ₦6,000` | **EXPANSION_RATCHET**| 3 | Max 10 active tickets (satellites enabled) |

### Non-Negotiable Capital Shields:
1. **~85% Bankroll Cash Shield**: Per-bet staking (3%–4%) combined with the 4-ticket cap guarantees ~85% of capital remains liquid and protected from simultaneous loss.
2. **Hard Stop-Loss Floor**: If True Equity breaches `< ₦100` or drops `50%` below starting capital, the engine triggers a hard emergency termination.
3. **Consecutive Failure Alert**: If 3 bet submission attempts fail consecutively, self-healing triggers; if 6 fail, the engine aborts to protect against site redesigns.

---

## 6. Critical Engineering Gotchas & Invariants (DO NOT REVERT)

1. **Native Mobile Touch Dispatch (`element.tap()`):**
   SportsExchange's mobile web app operates with `has_touch=True`. Standard desktop `page.mouse.click()` or `click(force=True)` **will NOT trigger odds selections**. Always use `element.tap()` (with fallback to `click(force=True)`).
2. **Astro Preloader Overlay (`z-[99999999]`):**
   SportsExchange injects an `<astro-island component-export="Preloader">` that covers the entire screen. `parser.clean_page(page)` removes this overlay. Always run `clean_page()` before UI interactions.
3. **Analytics & Ad Tracker Route Aborting:**
   Nigerian ISP latency causes `page.goto()` to hang indefinitely on third-party tracking pixels. [runner.py](file:///c:/Users/Zaddy/Documents/Analyst/engine/runner.py) aborts `google-analytics`, `doubleclick`, `facebook`, `bing`, `t.co`, and `opera` tracking requests.
4. **Phone Login Format:**
   `.env` `EXCHANGE_USERNAME` must be a 10-digit number. If provided with a leading `0` (11 digits), [bettor.py](file:///c:/Users/Zaddy/Documents/Analyst/engine/bettor.py) strips the leading zero automatically to match the input mask.
5. **Betslip Drawer Scoping:**
   Do not query generic `div[class*="drawer"]`—SportsExchange has a hidden standings drawer that matches this selector. Always scope to `[data-testid="betslip-header"]` and its parent tree.
6. **Unified `--dry-run` and `dry_fire` Flag:**
   `bettor.execute_ticket()` checks `if dry_fire or dry_run:` to ensure that `--dry-run` halts before the final "PLACE BET" tap, saves screenshot proof, and clears the slip without deducting money.
7. **Settled Bets Endpoint:**
   Settled bets can be retrieved via HTTP from:
   `/en-ng/my-bets/virtuals/settled?_data=routes%2F%28%24locale%29.my-bets.virtuals.%24betsType`
8. **Virtual Odds Do NOT Drift / Shift Dynamically:**
   Virtual football odds are static algorithmic constants determined by the RNG model per matchup—they do not float or drift like real sports markets. If the pre-click odds check detects a mismatch, it is purely a **UI Market Tab Lag** (e.g. the SPA has not finished switching from `1X2` to `Double Chance`). The engine self-heals by re-asserting the round and market tabs.

---

## 7. How to Run the Engine

Always activate virtual environment first:
```powershell
# 1. Run live dry-fire test (0 real money, captures UI screenshot evidence)
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative --dry-run --max-rounds 1

# 2. Run continuous live autonomous betting (real money)
.venv\Scripts\python -u -m engine.runner --profile ultra_conservative

# 3. Fast unauthenticated HTTP discovery diagnostics
.venv\Scripts\python scratch/test_discovery_client.py
```

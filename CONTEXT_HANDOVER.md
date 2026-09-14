# PROJECT CONTEXT & HANDOVER: EXCHANGE VIRTUAL VALUE BETTING ENGINE

## 1. Executive Summary & Current State
* **Platform**: SportsExchange Nigeria Scheduled Virtual Football.
* **Leagues (4)**:
  * **Premier League (England - league_en)**: 20 teams, 10 matches/round.
  * **Primera Liga (Spain - league_es)**: 20 teams, 10 matches/round.
  * **Serie League (Italy - league_it)**: 20 teams, 10 matches/round.
  * **Bundes League (Germany - league_de)**: 18 teams, 9 matches/round.
* **Verified Bankroll**: **₦864.96** Cash balance (+ ₦0.00 in-play = **₦864.96** True Equity; up from ₦512.96 initial deposit, +68.6% net return).
* **Active Profile**: `ultra_conservative` (High-Probability Bedrock Shield tier).
* **Architecture**: Unified Rolling Master Board (Cross-League & Cross-Week) with Fractional Kelly Staking.

---

## 2. Recent Critical Engineering Fixes (DO NOT REVERT)
0. **Multi-Stage Betslip Flush & Zero-Badge Assertion**:
   - Fixed broken Playwright `text='Clear All'` syntax to exact text matching across button/span/div.
   - Added JS DOM fallback for "Clear All" and individual card trash icons.
   - Added post-clear verification and hard page reload recovery if residual selections persist.
   - Added explicit "Singles" tab guard in drawer to prevent multi-bet accumulation.
1. **Empty Betslip Drawer Exact Close & State Guard**:
   - Discovered and implemented exact selector: `button[data-testid="betslip-header-title-close-icon"]`.
   - Backed by spatial fallback `(332, 84)` and `Escape` key dispatch.
   - Prevents an empty drawer from overlaying the viewport and blocking odds taps (which previously caused 15-minute rejection loops on Candidate #1).
   - Asserts drawer closure before fixture scanning and odds tapping.
2. **Post-Tap Betslip Badge Assertion**:
   - Asserts `<span data-testid="betslip-badge-count">` increments (`badge_count > 0`) after tapping odds.
   - If badge remains 0, retries with verified coordinate click before drawer opening.
3. **Stake Input Echo Assertion**:
   - Asserts `<input data-testid="stake-input">` value matches target stake string before triggering place bet. Auto-clears and retypes if mismatched.
4. **Relaxed Countdown Lockout**:
   - Replaced rigid 6s/10s timer cutoff with true 0s boundary (`slip_sec <= 0`).
   - Allows millisecond-level ticket submissions without artificial dropouts.
5. **Preserved Candidate #1 Edge (Zero Skipping / No Blacklisting)**:
   - Eliminates leaving alpha on the table; engine self-corrects modal state rather than blacklisting or dropping top-ranked candidates.
6. **Network Route Aborts for Promotional Popups**:
   - `page.route("**/*free2play*", lambda r: r.abort())`
   - `page.route("**/*premier-game*", lambda r: r.abort())`
   - `page.route("**/*exchange-core-account.workers.dev*", lambda r: r.abort())`
   - Permanently eliminates promotional overlays and iframes at the network level.
7. **Stateful In-Page Market Assertion**:
   - `select_market(category, tab_name)` asserts `<span data-testid="selected-market-name">` matches the target market before odds clicks.
8. **Vertical Week Header Bounding**:
   - Bounds fixture scraping strictly between `<p>Week X</p>` and `<p>Week X+1</p>` headers.
9. **Mobile Horizontal Tab Scrolling**:
   - Automatically brings off-screen sub-tabs into view before human touch calculations.
10. **High-Probability Profile & Sorting Calibration**:
    - Re-tuned `ultra_conservative` to `min_win_rate = 0.60`, `max_odds = 1.85`, and `min_edge = 0.05`.
    - Pool sorted by **Tier first, then Win Probability descending (`mu_phat`), then edge**.
11. **Match-Level Exposure Deduplication**:
    - Active exposure keyed by `f"{league} | {match_name}"` across rounds.

---

## 3. Tiered Staking & Ticket Construction (High-Probability Kelly)

### Conviction Tiers:
| Tier | Classification | Edge Criteria | Win Probability | Max Odds | Stake Sizing Formula |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Anchor** | ≥ 5.0% | ≥ 60.0% (Avg ~72%) | ≤ 1.85 (Avg ~1.59) | **4.0% base → up to 6.5%** scaled by edge |
| **2** | **Value** | ≥ 4.0% | ≥ 45.0% | ≤ 2.50 | **2.5% base → up to 4.0%** scaled by edge |
| **3** | **Speculative** | ≥ 3.0% | ≥ 35.0% | ≤ 3.50 | **2.0%** flat |
| **Double** | **Smart Double** | Combined edge | Joint prob ~52% | ≤ 3.00 | **2.5% base → up to 4.0%** |
| **Treble** | **Micro-Treble** | Cross-league | 3 Anchor legs | ≤ 4.20 | **₦10.00 platform floor** |

* **Proportional Staking**: Stake = `Current Bankroll × Edge Rate`. Compounds on wins and cushions drawdowns.
* **Humanization Steps**: All stakes snap to natural human increments (`10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 100...`).

---

## 4. Risk Management Rules
* **Pure True Equity (`Live Cash + In-Play Stakes`)**:
  - Tiers governed strictly by real equity:
    - `< ₦3,000`: Bedrock Shield (Ultra-conservative, max 2 tickets / cycle, max 4 concurrent active bets)
    - `₦3,000 – ₦5,999`: Core Growth (Max 2 tickets / cycle)
    - `≥ ₦6,000`: Expansion Ratchet (Max 3 tickets + satellite plays)
* **Hard Stop-Loss Floor**: Breaching `< ₦100` or 50% session loss immediately terminates engine.
* **Settlement Polling**: Checks live wallet balance on each cycle to capture returns immediately.
* **2,000-Path Monte Carlo Stress Test**: 0.00% risk of ruin, 99.1% net profit probability, median ending bankroll ₦1,107.46, average max drawdown ₦36.68 (7.8%).

---

## 5. Clean Startup & Monitoring Command
```bash
# Launch Live Autonomous Engine
& ".venv\Scripts\python.exe" -u engine/runner.py --profile ultra_conservative
```

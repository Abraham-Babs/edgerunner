# PROJECT CONTEXT & HANDOVER: EXCHANGE VIRTUAL VALUE BETTING ENGINE

## 1. Executive Summary & Current State
* **Platform**: SportsExchange Nigeria Scheduled Virtual Football.
* **Leagues (4)**:
  * **Premier League (England - league_en)**: 20 teams, 10 matches/round.
  * **Primera Liga (Spain - league_es)**: 20 teams, 10 matches/round.
  * **Serie League (Italy - league_it)**: 20 teams, 10 matches/round.
  * **Bundes League (Germany - league_de)**: 18 teams, 9 matches/round.
* **Verified Bankroll**: **₦622.76** (Cash balance verified from live wallet server).
* **Active Profile**: `ultra_conservative` (High-Probability Bedrock Shield tier).
* **Architecture**: Unified Rolling Master Board (Cross-League & Cross-Week) with Fractional Kelly Staking.

---

## 2. Recent Critical Engineering Fixes (DO NOT REVERT)
1. **Network Route Aborts for Promotional Popups**:
   - `page.route("**/*free2play*", lambda r: r.abort())`
   - `page.route("**/*premier-game*", lambda r: r.abort())`
   - `page.route("**/*exchange-core-account.workers.dev*", lambda r: r.abort())`
   - Permanently eliminates promotional overlays and iframes at the network level.
2. **Stateful In-Page Market Assertion**:
   - `select_market(category, tab_name)` asserts `<span data-testid="selected-market-name">` matches the target market before any odds buttons are clicked.
   - Eliminates the silent tab-shift bug where the UI remained on 1X2 while attempting to click alternative markets.
3. **Vertical Week Header Bounding**:
   - All 4 active weeks exist simultaneously in the page scroll.
   - `extract_current_market_rows` and `click_fixture_button` bound fixtures strictly between `<p>Week X</p>` and `<p>Week X+1</p>`.
   - Prevents top-to-bottom TreeWalker leakage where fixtures from the wrong round were clicked.
4. **Mobile Horizontal Tab Scrolling**:
   - On 360px mobile viewports, sub-tabs beyond the 2nd tab (e.g. *Home O/U 2.5*) are scrolled off-screen to the right.
   - `scroll_into_view_if_needed()` brings the element into view so `human_tap` calculates genuine touch coordinates and spatial jitter.
5. **High-Probability Profile & Sorting Calibration**:
   - Re-tuned `ultra_conservative` to `min_win_rate = 0.60`, `max_odds = 1.85`, and `min_edge = 0.05`.
   - Changed candidate pool sorting to rank by **Tier first, then Win Probability descending (`mu_phat`), then edge**.
   - Completely eliminates underdog bias (+30% EV on 40% probability) in favor of safe 70%–80% win-rate compounding.
6. **Match-Level Exposure Deduplication**:
   - Active exposure deduplication is keyed strictly by `f"{league} | {match_name}"` (ignoring round/week variation).
   - Prevents double-staking the same matchup across different rounds while unsettled.
7. **Resilient Rollover & Self-Healing Recovery**:
   - If a candidate fails pre-click or betslip validation, the engine evicts that edge and rolls over to the next candidate immediately with zero delay.
   - Replaced abrupt `sys.exit(1)` on consecutive failures with automated cache purge and clean page reloads.

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

* **Proportional Staking**: Stake = `Current Bankroll × Edge Rate`. Automatically compounds on gains and preserves capital on drawdowns.
* **Humanization Steps**: All stakes snap to natural human increments (`10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 100...`).

---

## 4. Risk Management Rules
* **Pure True Equity (`Live Cash + In-Play Stakes`)**:
  - Tiers governed strictly by real equity:
    - `< ₦3,000`: Bedrock Shield (Ultra-conservative, max 2 tickets / cycle, max 4 concurrent active bets)
    - `₦3,000 – ₦5,999`: Core Growth (Max 2 tickets / cycle)
    - `≥ ₦6,000`: Expansion Ratchet (Max 3 tickets + satellite plays)
* **Hard Stop-Loss Floor**: Breaching `< ₦100` or 50% session loss immediately terminates engine.
* **Settlement Polling**: Automatically checks live wallet balance on each cycle to capture returns immediately.
* **2,000-Path Monte Carlo Stress Test**:
  - Tested over 150 bets starting at ₦468: 0.00% risk of ruin, 99.1% net profit probability, median ending bankroll ₦1,107.46, average max drawdown ₦36.68 (7.8%).

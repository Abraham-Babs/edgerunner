# SportsExchange Virtual Leagues — Autonomous Value Betting Engine

An autonomous betting system that identifies and exploits statistical edges in SportsExchange's virtual football leagues. It runs continuously, cycles through four leagues, reads live odds directly off the screen, cross-checks them against a historical model, and places only bets where the numbers are genuinely in our favour.

---

## How It Works

### 1. The Edge Model
Before the engine ever starts, historical match data for each league is processed into a table of **confirmed edges** (`analysis/results/confirmed_edges.csv`). Each edge represents a matchup (e.g. *MAN vs ARS, Home Win*) where our model's estimated true win probability is meaningfully higher than what the bookmaker's odds imply. This is the mathematical foundation everything else is built on.

### 2. Live Odds Verification
The engine doesn't blindly follow the historical model. Every cycle, it scrapes the actual live odds off the SportsExchange page and checks whether the edge still holds at the current price. If the odds have shifted and the edge is gone, the selection is skipped.

### 3. Conviction Tiers & Fractional Edge-Scaled Kelly
Qualifying selections are graded into conviction tiers prioritizing **high win probabilities (60%–80%) and low odds (1.45–1.85)** to eliminate capital volatility:

| Tier | Name | Edge | Win Rate | Max Odds | Stake Sizing Formula |
|------|------|------|----------|----------|----------------------|
| 1 | Anchor | ≥ 5% | ≥ 60% (Avg ~72%) | ≤ 1.85 (Avg ~1.59) | **4.0% base → up to 6.5%** scaled by edge strength |
| 2 | Value | ≥ 4% | ≥ 45% | ≤ 2.50 | **2.5% base → up to 4.0%** scaled by edge strength |
| 3 | Speculative | ≥ 3% | ≥ 35% | ≤ 3.50 | **2.0%** flat |
| Multi | Smart Double | Combined | Joint prob ~52% | ≤ 3.00 | **2.5% base → up to 4.0%** |
| Multi | Micro-Treble | Cross-League | 3 Anchor legs | ≤ 4.20 | **Fixed ₦10** platform minimum |

Stakes are proportional to current bankroll (`Stake = Bankroll × Edge Rate`) and snap to natural human increments (`₦20, ₦25, ₦30, ₦35, ₦40, ₦50...`).

### 4. Unified Rolling Master Board (Cross-League & Cross-Week)
Instead of scraping one league at a time, the engine maintains an in-memory rolling Master Board:
- **Sliding Window Caching**: Retains active rounds (Weeks 1–4) and only scrapes newly unlocked rounds when an old round finishes. Reduces DOM operations by **~75%**.
- **Cross-League & Cross-Week Doubles**: Combines independent selections across different leagues (e.g. England + Italy) to eliminate intra-matchday correlation.
- **Smart Micro-Trebles**: Combines 3 independent high-probability legs across 3 distinct leagues, capped at ≤ 4.20 odds, staked at ₦10.
- **Anchor Imminent Priority**: Primary Anchor singles prioritize imminent rounds (Weeks 1–2) for rapid 90–180s capital turnover.
- **Probability-First Sorting**: Candidate pool sorts by **Tier first, then Win Probability descending (`mu_phat`), then Edge**, preventing high-odds underdogs from starving safe favorites.

### 5. In-Betslip 3-Point Validation & Human Emulation
- **Stateful Market Assertion**: Checks `<span data-testid="selected-market-name">` to guarantee the view is on the correct market tab before tapping odds.
- **Vertical Week Bounding**: Bounds fixture scraping between `<p>Week X</p>` and `<p>Week X+1</p>` headers, preventing top-to-bottom TreeWalker leakage across the 4-week page scroll.
- **Mobile Horizontal Tab Scrolling**: Automatically brings off-screen sub-tabs into view before executing natural human touch coordinates and jitter.
- **Pre-Click Parity & Zero-Tolerance Slip Validation**: Asserts button odds on screen match expected odds within ±0.02. In the betslip drawer, it asserts match name, selection, combined odds, and a minimum 6s timer cutoff.

### 6. Risk Management & Live Scorecard
- **Pure Equity Scaling**: Tiers governed strictly by `true_equity` (`Live Cash + In-Play Stakes`):
  - `< ₦3,000`: Bedrock Shield (Ultra-conservative, max 2 tickets / cycle, max 4 concurrent active bets)
  - `₦3,000 – ₦5,999`: Core Growth (Max 2 tickets / cycle)
  - `≥ ₦6,000`: Expansion Ratchet (Max 3 tickets + satellite plays)
- **Hard Stop-Loss Floor**: Exits immediately if capital drops below ₦100 or 50% deposit loss.
- **Match-Level Exposure Deduplication**: Deduplicates active exposure strictly by `f"{league} | {match_name}"` across rounds.
- **Session Scorecard**: Prominently displays starting balance, current cash, net P&L in Naira and %, active in-play tickets, and true equity on every cycle.
- **Network Resilience & Self-Healing**: Automatic pause and reconnection retry on DNS or connection dropouts; auto-reloads page and flushes cache on unexpected errors instead of hard terminating.

---

## Running the Engine

```bash
# Live autonomous engine (Ultra-Conservative)
.venv\Scripts\python -u engine/runner.py --profile ultra_conservative

# Live dry-run (scrapes live odds, validates betslip DOM, zero real money spent)
.venv\Scripts\python -u engine/runner.py --profile ultra_conservative --dry-run
```

---

## Project Structure

```
engine/
  runner.py            — Orchestrator. Manages Master Board sync, cycles, and risk scorecard.
  master_board.py      — In-memory sliding window cache for all 4 leagues and visible rounds.
  ticket_builder.py    — Assembles singles, cross-league doubles, and micro-trebles with Kelly sizing.
  bettor.py            — Physically executes tickets on the SportsExchange mobile UI with 3-point validation.
  parser.py            — Scrapes live fixtures, odds, and round timers with vertical week bounding.
  edge_matcher.py      — Loads confirmed positive-EV lookup edges and validates live odds.
  human_interaction.py — Spatial jitter, natural pauses, and human touch simulation.
  config.py            — System thresholds, profiles, and league endpoints.
```

---

## Key Operating Targets

- **Current Verified Cash Baseline**: ₦622.76
- **Anchor Sizing**: Dynamic 4.0% – 6.5% of bankroll based on edge strength (₦25 – ₦35)
- **Micro-Treble**: ₦10 flat stake on 3 cross-league anchor legs (≤ 4.20 odds)
- **Active Exposure**: Max 4 concurrent bets (Ultra-Conservative)
- **Monte Carlo Stress Tested**: 2,000 simulated 150-bet sessions: 0.00% risk of ruin, 99.1% profit probability, average max drawdown ₦36.68 (7.8%).
- **Safety Safeguards**: 7 consecutive losses = 12-min rest; Hard floor = ₦100 or 50% deposit loss

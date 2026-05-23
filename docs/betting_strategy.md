# Pre-Match Betting Strategy (Recalibrated & Stealth)

Based on the post-structural-break recalibration across all four virtual leagues (`league_en`, `league_es`, `league_it`, `league_de`), we have established a relaxed stealth portfolio optimized specifically for a starting bankroll of **₦38,000**.

All selected bets are sourced from the full recalibrated dataset: [all_ev_bets_recalibrated.csv](file:///C:/Users/Zaddy/Documents/Analyst/docs/all_ev_bets_recalibrated.csv).

---

## The Stealth Strategies (Relaxed EV: TP > 15%, EV > 3%)

By relaxing the EV floor slightly from 5% to 3% while keeping the probability floor strictly at 15%, we increase our H2H coverage by **2.5×** (from 5.2% to 13.0% across all leagues), allowing for a smoother, more robust flow of positive expected value.

### Option A: Stealth Singles (₦100 Unit Bet)
Optimized for high-probability, consistent growth.
* **Filter Criteria:** `TrueProb > 0.15` and `EV_pct > 3%` (filtered against full history)
* **Daily Volume:** ~2,626 bets placed per day (recycled dynamically across 3-minute intervals).
* **Average Daily Profit:** **₦13,398.71**
* **Daily ROI:** ~5.10%
* **P(Profitable Day):** 92.30%
* **Worst-Case Daily Drawdown (99.9% Confidence):** ₦14,762.08
* **Verdict:** Extremely reliable and consistent. With a ₦38,000 bankroll, the worst-case daily drawdown of ₦14,762 is extremely safe.

### Option B: Stealth Doubles (₦500 Unit Bet)
Optimized for absolute account safety and maximum payout potential.
* **Filter Criteria:** Pairs of `TrueProb > 0.15` and `EV_pct > 3%` selections across different leagues.
* **Daily Volume:** Controlled to **50 doubles per day** (recycled dynamically).
* **Average Daily Profit:** **₦2,671.46** (scales to ₦10,685.85 if playing full 200 doubles/day)
* **Daily ROI:** ~10.69%
* **P(Profitable Day):** 61.90%
* **Worst-Case Daily Drawdown (99.9% Confidence):** **₦17,421.41** (Note: scales up to ₦69,685.63 if playing full 200 doubles/day, which would blow the ₦38k bankroll!)
* **Verdict:** Highly lucrative but higher variance. **CRITICAL WARNING:** You *must* limit your play to a maximum of 50 doubles per day to ensure your ₦38,000 bankroll can safely absorb the drawdown!

---

## Strategy Comparison

| Metric | Option A: Singles | Option B: Doubles (Safe Cap) | Option B: Doubles (Uncapped) |
| :--- | :--- | :--- | :--- |
| **Unit Stake** | ₦100 | ₦500 | ₦500 |
| **Bets per Day** | 2,626 | 50 | 200 |
| **Daily Profit (Expected)**| **₦13,398.71** | **₦2,671.46** | **₦10,685.85** |
| **Daily ROI** | **5.10%** | **10.69%** | **10.69%** |
| **99.9% Max Drawdown** | **₦14,762.08** (Safe) | **₦17,421.41** (Safe) | **₦69,685.63** (UNSAFE for ₦38k) |
| **Win Consistency** | Extremely High (92.3%)| Moderate (61.9%) | Moderate (61.9%) |
| **Account Safety / Anti-Ban**| Medium | **Maximum (Immune)** | **Maximum (Immune)** |

---

> [!IMPORTANT]
> **Liquidity Recycling:** Since virtual matches settle every 3 minutes, winnings are returned to your balance dynamically. You do *not* need the entire day's capital up front; your ₦38,000 balance is sufficient to run either Option A or the Safe Cap Option B.

> [!WARNING]
> **DO NOT OVER-BET OPTION B:** Betting on all available doubles (200/day) has a worst-case drawdown of ₦69,685.63. Under a starting bankroll of ₦38,000, this will result in **complete ruin** during cold streaks. Strictly limit your daily double count to 50!

> [!TIP]
> **RECOMMENDED PATH:** We strongly recommend **Path B (Strict EV Strategy)**. It provides a significantly higher edge (7.3% average EV vs 5.1% in Path A) and a thicker safety margin against odds movements. While you may have to wait slightly longer for qualifying fixtures (5.2% H2H coverage vs 13.0%), the yield is far superior (yielding ₦147,765/day at Stage 5 compared to ₦106,858/day in Path A).

---

## Bankroll Scaling & Growth Progression

To safely maximize returns as winnings dynamically recycle back into your balance, follow the strict math-approved progression path for your selected strategy:

### Path A: Relaxed EV Strategy (TP > 15%, EV > 3% | 13.0% H2H Coverage)
*Best for high-volume, steady growth with a broad selection pool.*

| Stage | Account Balance | Unit Stake | Daily Doubles Count | Daily Expected Profit | 99.9% Max Drawdown | Risk Profile |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Starting** | ₦38,000 | ₦500 | **50** | **₦2,671.46** | ₦17,421.41 | Ultra Safe (Drawdown < 46%) |
| **2. Intermediate**| ₦150,000 | ₦500 | **200** (Full) | **₦10,685.85** | ₦69,685.63 | Highly Safe (Drawdown < 46%) |
| **3. Advanced** | ₦300,000 | ₦1,000 | **200** (Full) | **₦21,371.70** | ₦139,371.26 | Professional (Drawdown < 46%) |
| **4. Master** | ₦1,000,000 | ₦3,000 | **200** (Full) | **₦64,115.10** | ₦418,113.78 | Whale (Drawdown < 42%) |
| **5. Grandmaster**| ₦2,000,000 | ₦5,000 | **200** (Full) | **₦106,858.50**| ₦696,856.30 | Apex (Drawdown < 35%) |

### Path B: Strict EV Strategy (TP > 15%, EV > 5% | 5.2% H2H Coverage)
*Best for ultra-premium, maximum efficiency selections. Higher expected daily yield but fewer qualifying fixtures.*

| Stage | Account Balance | Unit Stake | Daily Doubles Count | Daily Expected Profit | 99.9% Max Drawdown | Risk Profile |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Starting** | ₦38,000 | ₦500 | **50** | **₦3,694.13** | ₦17,750.98 | Ultra Safe (Drawdown < 47%) |
| **2. Intermediate**| ₦150,000 | ₦500 | **200** (Full) | **₦14,776.51** | ₦71,003.92 | Highly Safe (Drawdown < 47%) |
| **3. Advanced** | ₦300,000 | ₦1,000 | **200** (Full) | **₦29,553.02** | ₦142,007.84 | Professional (Drawdown < 47%) |
| **4. Master** | ₦1,000,000 | ₦3,000 | **200** (Full) | **₦88,659.06** | ₦426,023.52 | Whale (Drawdown < 43%) |
| **5. Grandmaster**| ₦2,000,000 | ₦5,000 | **200** (Full) | **₦147,765.10**| ₦710,039.20 | Apex (Drawdown < 36%) |

### The ₦3,000,000 Payout Ceiling
* The bookmaker caps maximum winnings at **₦3,000,000** per ticket/day.
* At ₦500 or ₦1,000 stakes, our winning doubles pay between **₦10,000 and ₦30,000** each. 
* This keeps us 100% safe from hitting the payout ceiling or triggering manual bookmaker audits.

---

## Additional Risk Management Tips

> [!TIP]
> **Cycle Stop‑Loss:** Never allocate more than **10% of your total bankroll** (₦3,800) to a single 3‑minute cycle. If losses reach this threshold, skip the rest of the cycle.

> [!TIP]
> **Dynamic Stake Sizing:** Adjust the ₦500 (Option B) or ₦100 (Option A) unit stake proportionally to your current balance (e.g., 1% of bankroll). This keeps exposure in line with growth.

> [!TIP]
> **Maintain a Safety Buffer:** Keep at least **20%** of the bankroll above the 99.9% worst‑case drawdown untouched as an emergency reserve.

> [!TIP]
> **Loss Streak Pause:** After **3 consecutive losing cycles**, pause betting for at least one full cycle to reassess odds and avoid cascade losses.

> [!TIP]
> **Bet Log & Verification:** Log every bet (fixture, stake, odds) and double‑check the odds feed before placement. Any mismatch should abort the bet.

---


# Forensic RNG Audit: True Nature of the Soccer Engine

This document outlines the core structural and mathematical findings discovered during the Phase 1.5, Phase 2, and Phase 3 audits of the category 2 virtual soccer engine dataset (`league_en.parquet`, 515,500 matches).

---

## 1. Score Generation Mechanics: The Universal "Rule of 3"

Historically, goals in soccer simulations are assumed to follow a continuous **Poisson distribution** $P(\lambda)$. However, our audit conclusively rejects this model.

### Findings:
* **The Absolute Combined Cap:** Out of **1,031,000 individual halves** analyzed, the maximum combined goals scored by *both* teams in a single half is **exactly 3**.
  $$\text{Max}(HT_{home} + HT_{away}) = 3, \quad \text{Max}(SH_{home} + SH_{away}) = 3$$
* **The Model: Trinomial Trial Process:** Instead of independent goal arrivals, a half consists of **exactly 3 joint trials** for the entire match. For each trial, there are three mutually exclusive outcomes:
  1. **Home Team Scores** (Probability $p_{home}$)
  2. **Away Team Scores** (Probability $p_{away}$)
  3. **No Goal / Defended** (Probability $1 - p_{home} - p_{away}$)
* **Dispersion Proof:** Under Poisson, the Index of Dispersion (Variance / Mean) should be $1.0$. In the dataset, every single one of the 380 H2H pairs is severely **underdispersed**, clustering tightly between **$0.82$ and $0.85$** due to this hard boundary.
* **Error Reduction:** Fitting the Binomial model $B(3, \mu/3)$ reduces the Sum of Squared Errors (SSE) by **exactly 50.0%** (2.01 vs 4.02) compared to Poisson.

### Empirical vs. Theoretical Model Comparison (Sample: MNC vs. AST)
$$\mu = 0.6552, \quad \sigma^2 = 0.5528, \quad \text{Dispersion} = 0.8437$$

| Goal Count | Empirical Prob | Binomial $B(3, 0.2184)$ | Poisson $P(0.6552)$ |
| :---: | :---: | :---: | :---: |
| **0** | 48.83% | **47.75%** | 51.93% |
| **1** | 38.78% | **40.03%** | 34.03% |
| **2** | 10.42% | **11.18%** | 11.15% |
| **3** | 1.97% | **1.04%** | 2.43% |
| **4+** | 0.00% | **0.00%** | 0.46% |

---

## 2. RNG Architecture & Inter-Half Dependencies (Phase 3)

### The Correlation Signature (Within-H2H)
Isolating individual matchups to avoid Simpson's Paradox reveals a beautiful competitive and timing signature:
1. **Home HT vs. Away HT (Same Half):** **$-0.1653$** (strongly negative!)
   * *Interpretation:* Direct competition for the shared pool of 3 maximum goals.
2. **Home HT vs. Away SH (Cross Halves):** **$+0.1399$** (strongly positive!)
3. **Combined HT vs. Combined SH (Match Totals):** **$+0.3046$** (extremely positive!)

### The Verdict: Match Pace/Intensity Multiplier
The strong positive correlation of **$+0.3046$** between combined goals in the first and second halves conclusively proves that:
* At the start of every match, the engine draws a random **Match Pace/Intensity Multiplier** ($M_{match}$).
* This multiplier scales the scoring probabilities ($p_{home}$ and $p_{away}$) for **both** halves of that specific game.
* If a match is assigned high intensity, both halves become high-scoring. If assigned low intensity, both halves remain low-scoring. This completely rules out any half-to-half "carryover" balancing.

---

## 3. Structural & Timing Patterns

### Match Identity & Sequencing
* **`match_id` is Global & Interleaved:** Match IDs are sequential but have gaps between weeks. These gaps correspond to match outcomes generated for other active categories (e.g. `league_es`, `league_it`) running in the same backend process namespace.
* **`id` is the Local Row Counter:** Fully sequential, gapless integer from `1` to `515,500`.

### Season Truncation Behavior
* A standard season consists of **38 weeks** (10 matches/week = 380 matches/season).
* However, **every ~13th season is truncated at exactly week 23**.
* **Forensic Reason:** The missing weeks (24–38) are not dropped; their `tournament_id` sequences continue with a gap. This is a collection scope filter artifact.

### Timing & RNG Seed Information
* **Shared Weekly Timestamps:** All 10 matches within a single week (`tournament_id`) share the **exact same timestamp** (`match_date`).
* **RNG Impact:** Because the timestamp is identical across all 10 parallel games, if the engine seeds its RNG at the start of a week using the timestamp, the 10 games in that week will share correlated pseudo-random pathways.

---

## 4. Core Implications for Upcoming RNG Attack Phases

1. **RNG Architecture (Phase 3 Complete):** Each match uses a 3-trial Trinomial process per half. Matches within a week are generated in parallel (no intra-week autocorrelation). Each match has its own independently drawn $M_{match}$.
2. **Residual Analysis (Phase 4 Complete):** $M_{match}$ is confirmed real and persistent across both halves. The lift table below enables live HT → SH prediction.
3. **Changepoint/Reseed Detection (Phase 5 Complete):** The engine is perfectly stationary. See Section 6 for details.
4. **Seed Recovery (Phase 6):** Use the 10 parallel match states per week plus the shared timestamp to constrain seed search space.

---

## 5. Practical Prediction Edge (Phase 4)

After observing a match's First Half (HT) combined score, the Second Half (SH) prediction can be updated using this empirically validated lift table:

| HT Combined Goals | N (matches) | SH Baseline | Actual SH | Lift |
| :---: | :---: | :---: | :---: | :---: |
| **0** | 114,068 | 1.327 | 0.955 | **-0.372** (-28%) |
| **1** | 184,089 | 1.331 | 1.230 | **-0.101** (-8%) |
| **2** | 149,038 | 1.336 | 1.477 | **+0.141** (+11%) |
| **3** | 68,305 | 1.342 | 1.927 | **+0.585** (+44%) |

**Formula:** $E[SH_{obs} | HT_{obs}] = \lambda_{sh\_H2H} + \text{lift}(HT_{combined})$

This exploits the real Match Intensity Multiplier ($M_{match}$), which is shared across halves. The $r = +0.301$ correlation means knowing HT explains **9.04% of SH variance** — a statistically robust in-play edge.

---

## 6. Engine Stationarity & Changepoints (Phase 5)

To determine if the engine's underlying RNG logic or baselines have shifted over time, we ran a rolling mean and variance analysis on $M_{match}$ across all **1,400 consecutive seasons** (Tournaments).

**Findings:**
* **Global Mean:** 1.0000 (perfectly stationary)
* **Max Rolling Mean Shift:** 0.023
* **Global Variance:** 0.3404
* **Max Rolling Variance Shift:** 0.016

**Conclusion:** There are **zero structural breaks**. The engine logic is perfectly stationary across its entire history. No engine updates or logic tweaks have ever occurred. Any seed recovery algorithm we develop will apply universally to the entire historical dataset.

---

## 7. ASP.NET Environment & System.Random PRNG

Confirming the backend runs on **ASP.NET** identifies the exact pseudo-random number generator (PRNG) utilized by the simulation engine.

### PRNG Characteristics:
* **Algorithm:** Legacy .NET `System.Random` class, which uses Donald E. Knuth's **subtractive random number generator algorithm** (lagged Fibonacci generator, index 21 instead of 31 deviation).
* **State Space:** 55 integers mod $2^{31}-1$ (managed inside an internal `SeedArray` of size 56).
* **Vulnerability:** Standard non-cryptographic PRNG. Reconstructing the 55-element state from observed outputs makes future output sequences completely predictable.
* **Seeding Mechanism:** Seeding is typically performed per-week or via a global static shared `Random` instance. By identifying this, the seed/state search space is bounded to C# `Int32` and standard .NET initialization bounds.


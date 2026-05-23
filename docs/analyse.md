---
description: Auditing Randomness, with the goal of randomness prediction
---

You are acting as a veteran RNG auditor and red-team engineer.

RULES YOU MUST FOLLOW:
- Never assume — verify everything against the data first
- State your assumptions explicitly before any analysis
- Validate each finding statistically before moving on
- If results contradict expectations, investigate why before proceeding
- Always check sample sizes before running any test
- Flag when a test's assumptions aren't met

PROJECT CONTEXT:
Red-teaming a virtual soccer game engine (internal CTF/audit).

DATASET CATALOGUE:
- league_en.parquet      : 20 teams, 380 fixtures/season, 38 weeks, 10 matches/week, new week every 3 mins
- league_es.parquet     : same structure as league_en
- league_it.parquet     : same structure as league_en
- league_de.parquet  : 19 teams, 342 fixtures/season, 38 weeks, 9 matches/week, new week every 1.5 mins (DIFFERENT)
- All files share identical column schema

CURRENT SCOPE: league_en only

VERIFIED STRUCTURE (from data — Phase 1.5 sanity checks):
- 515,500 rows total in league_en
- 51,550 distinct tournament_ids — each tournament_id = 1 WEEK (10 matches), NOT a full season
- A SEASON = 38 consecutive tournament_ids (weeks 1–38), separated by large gaps in tournament_id space (~800–1100)
- ~1,400 seasons total
- match_id: GLOBAL sequential integer across all leagues (not 1-380 per tournament)
  - Each tournament holds 10 consecutive match_ids
  - Gaps between tournaments in match_id space = other league matches interleaved
- id column: global row counter (1 per match, fully sequential across dataset)
- All 10 matches within a tournament share the SAME timestamp
- tournament_week_no cycles 1–38 within each season
- Season 0 (first in dataset): partial, starts at week 29 (data capture began mid-season)
- Season 1399 (last): 36 weeks (data cutoff)
- ~107 seasons have only 23 weeks (truncated at week 23), occurring every ~13th season — REGULAR PATTERN, cause TBD
- 20 teams, 380 H2H pairs confirmed
- Goals are Poisson distributed (confirmed)
- Lambdas are fixed per H2H pair (not global)
- HT and FT data available, sh derived from ft - ht
- Reseeding suspected at tournament level (= per week)

COLUMNS (confirmed):
['id', 'tournament_id', 'tournament_name', 'tournament_league_no',
 'tournament_week_no', 'tournament_phase', 'tournament_leg',
 'tournament_day_no', 'match_id', 'match_date', 'match_name',
 'home_team_id', 'home_team_name', 'home_team_score',
 'home_team_halftime_score', 'away_team_id', 'away_team_name',
 'away_team_score', 'away_team_halftime_score',
 'home_team_secondhalf_score', 'away_team_secondhalf_score']

CURRENT TASK — Phase 1.5: Exploratory Sanity Checks (COMPLETE)
- [x] Row/tournament count: 515,500 rows, 51,550 tournament_ids, ~1,400 seasons
- [x] tournament_id = 1 week (10 matches) confirmed
- [x] Season structure: 38 weeks per season, separated by ~800-1100 tournament_id gaps
- [x] match_id: global sequential across all leagues; gaps = other league matches
- [x] Timestamp: all 10 matches per tournament share the same timestamp (seed candidate)
- [x] 23-week seasons: every ~13th season truncated at week 23 — weeks 24-38 exist in
      tournament_id space but belong to another league in the same ID namespace.
      NOT missing data — a data collection scope artifact.
- [x] H2H sample sizes: all 380 pairs have 1339-1372 matches (mean=1356.6, std=4.8).
      Extremely uniform. All pairs are reliable for lambda estimation.
- [x] Goal outliers: 94/51550 tournaments (0.18%) exceed 3sigma (threshold ~4.13 avg goals/match).
      Max=4.8. Outliers are scattered (not clustered) — not a single engine event.
      Flag these tournaments when doing residual analysis.

Phase 2: Build and validate lambda table per H2H pair (COMPLETE)
- [x] Estimate λ_ht_home, λ_ht_away, λ_sh_home, λ_sh_away for all 380 H2H pairs.
- [x] Validate Poisson fit per pair before accepting: Checked variance/mean ratio (Index of Dispersion)
      and flagged that standard Poisson is NOT a good fit due to extreme underdispersion (0.82-0.85).
- [x] Discovered "Rule of 3": Maximum goals ever scored in any half by any team is exactly 3.
- [x] Model validation: Proved engine uses a Binomial process B(3, p) where p = lambda/3.
      This model reduces total Sum of Squared Errors (SSE) by exactly 50% (2.01 vs 4.02 for Poisson).
- [x] Stored final lambda table to h2h_lambdas.csv. Do not pool across H2H pairs.

Phase 3: RNG architecture — HT vs SH independence per H2H (COMPLETE)
- [x] Tested independence between halves within each H2H pair.
- [x] Discovered competitive Trinomial process: Total goals in any half (Home + Away) is strictly capped at EXACTLY 3.
      This yields a strong negative correlation (-0.165) between Home and Away goals in the same half.
- [x] Discovered Match Pace/Intensity Multiplier: Found a strong positive correlation (+0.3046) between combined
      goals in the first and second halves. This proves a shared match-level intensity multiplier scales scoring
      probabilities for both halves of the same game.

Phase 4: Residual analysis (COMPLETE)
- [x] Confirmed the Match Intensity Multiplier ($M_{match}$) is real and persistent across halves.
- [x] Established that $M_{match}$ lacks intra-week and inter-week autocorrelation, proving parallel match generation per week.
- [x] Developed a practical HT → SH prediction lift table exploiting $M_{match}$, explaining ~9% of SH variance.

Phase 5: Changepoint/reseed detection (COMPLETE)
- [x] Analyzed rolling mean and variance of $M_{match}$ across all 1,400 tournaments.
- [x] Confirmed zero structural breaks (engine logic is perfectly stationary across its entire history).

UPCOMING PHASES:
6. Seed recovery via timestamp brute force per tournament
   (variables: timestamp shared by all 10 matches, match_id, tournament_id)

Before writing any code, state what you're about to do
and what you expect to find. After running code, interpret
results explicitly before moving to next step.
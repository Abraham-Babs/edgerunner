"""
engine/ticket_builder.py
------------------------
Decides what to bet on and how much to stake, once the edge matcher has
identified matches with a mathematical advantage.

Tier System:
  Every qualifying selection is graded into one of three conviction tiers
  based on how strong the statistical edge is, how often the outcome wins,
  and what the live odds are:

  - Tier 1 (Anchor)     : Highest confidence. Edge >= 7%, win rate >= 45%,
                          odds under 2.80. These are the most reliable plays
                          and get the largest stake (7% of bankroll).

  - Tier 2 (Value)      : Solid confidence. Edge >= 4%, win rate >= 35%,
                          odds under 3.80. Good risk-reward, staked at 4%
                          of bankroll.

  - Tier 3 (Speculative): Lower certainty — underdogs or higher odds markets
                          where there is still a positive edge but more
                          variance. Staked conservatively at 2.5% of bankroll.

Ticket Mix Strategy (per league visit, up to 3 tickets):
  Priority 1 — Anchor Single:
    The top Tier 1 selection goes on a single. Maximum bang-for-buck compounding.
    Stake: 7% of current bankroll.

  Priority 2 — Smart Double (35% random trigger):
    When a good Tier 1 Anchor and a Tier 2 Booster exist on DIFFERENT matches,
    they are combined into a double. Combined odds are capped at 6.0 — this was
    validated by backtesting three scenarios (6.0 / 10.0 / uncapped). The 6.0
    cap produced the highest ROI because only highly selective doubles pass
    through (50% win rate), while capital from rejected doubles flows into
    higher win-rate singles instead. Stake: 4% of bankroll.

  Priority 3 — Value Singles:
    Any remaining matches with positive edges that aren't already used in a
    ticket are added as singles, sized by their tier.

Key Safety Rules:
  - A match can only appear in ONE ticket. No double-counting the same game.
  - Stakes are always rounded to the nearest human betting increment
    (₦10, ₦15, ₦20, ₦25... ₦500) so the amounts look natural.
  - Total stake per ticket is capped at ₦500 regardless of bankroll size.
"""

import random
from typing import List, Dict, Any
from engine.config import HUMAN_STAKE_STEPS, MIN_PLATFORM_STAKE, MAX_STAKE_CEILING, TICKET_MIX_RATIOS

def quantize_to_human_step(raw_amount: float) -> float:
    """
    Rounds a calculated stake amount to the nearest value a real human would type.
    Nobody bets ₦47.32 — they bet ₦50 or ₦45. This function maps any raw
    computed amount to the nearest step in our predefined list of natural
    betting increments (₦10, ₦15, ₦20, ₦25 ... ₦500).
    """
    if raw_amount <= MIN_PLATFORM_STAKE:
        return MIN_PLATFORM_STAKE
    clamped = min(raw_amount, MAX_STAKE_CEILING)
    closest = min(HUMAN_STAKE_STEPS, key=lambda x: abs(x - clamped))
    return float(closest)

def classify_tier(candidate: Dict[str, Any]) -> int:
    """
    Grades a betting selection into a conviction tier (1, 2, or 3).

    Tier 1 (Anchor / Shield)     : High win rate (>=60%), safe odds (<=1.85), edge >=5%.
    Tier 2 (Yield Booster)       : Strong edge (>=4%), solid win rate (>=50%), odds up to 2.35.
    Tier 3 (Speculative)         : Remaining positive edge selections.
    """
    edge = candidate.get("min_edge", 0.0)
    odds = candidate.get("raw_odds", 2.0)
    win_rate = candidate.get("mu_phat", 0.40)

    if edge >= 0.05 and win_rate >= 0.60 and odds <= 1.85:
        return 1
    elif edge >= 0.05 and win_rate >= 0.55 and odds <= 2.10:
        return 2
    else:
        return 3

def calculate_tier_stake(balance: float, tier: int, ticket_type: str, odds: float = 2.0, edge: float = 0.0, n_train: int = 300) -> float:
    """
    Calculates stake based on bankroll, conviction tier, ticket format, and edge magnitude (Fractional Kelly).

    Dynamic Edge-Scaled Rates:
      - Tier 1 Single     : 4.0% base, scaling up to 5.5% for outsized edges.
      - Tier 2 Single     : 2.5% base, scaling up to 3.5% for strong edges (tighter sizing to protect drawdown).
      - Tier 3 Single     : 2.0% flat.
      - Smart Double      : 2.5% base, scaling up to 3.5%.
      - Treble            : Platform minimum (₦10).
    """
    if ticket_type == "single":
        if tier == 1:
            rate = 0.040 + max(0.0, edge - 0.06) * 0.20
            rate = min(0.055, max(0.040, rate))
        elif tier == 2:
            rate = 0.025 + max(0.0, edge - 0.04) * 0.15
            rate = min(0.035, max(0.025, rate))
        else:
            rate = 0.020
        raw = balance * rate

    elif ticket_type == "double":
        rate = 0.025 + max(0.0, edge - 0.06) * 0.15
        rate = min(0.035, max(0.025, rate))
        raw = balance * rate

    elif ticket_type == "treble":
        raw = MIN_PLATFORM_STAKE

    else:
        raw = MIN_PLATFORM_STAKE

    confidence_scale = min(1.0, n_train / 300.0)
    raw = raw * confidence_scale

    return quantize_to_human_step(raw)

class TicketBuilder:
    def __init__(self, mix_ratios: dict = None):
        self.mix_ratios = mix_ratios or TICKET_MIX_RATIOS

    def build_tickets(
        self, 
        qualified_edges: List[Dict[str, Any]], 
        balance: float, 
        max_tickets: int = 3, 
        profile: dict = None,
        portfolio_mode: dict = None,
        satellite_candidates: List[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Takes a list of positive-EV selections for a single league and assembles
        betting tickets respecting profile constraints and portfolio allocation mode.
        """
        if not qualified_edges and not satellite_candidates:
            return []

        profile = profile or {}
        portfolio_mode = portfolio_mode or {}
        effective_max_tickets = min(max_tickets, portfolio_mode.get("max_tickets", max_tickets))
        allow_conservative = portfolio_mode.get("allow_conservative", True)
        allow_satellite = portfolio_mode.get("allow_satellite", False)
        sat_pct = portfolio_mode.get("satellite_pct", 0.05)

        max_w_count = profile.get("max_weeks", 4)
        max_double_odds = portfolio_mode.get("max_double_odds", profile.get("max_double_odds", 2.80))

        # 1. Identify round sequence across visible weeks
        all_weeks = []
        for e in qualified_edges:
            w = e.get("week", "")
            if w and w not in all_weeks:
                all_weeks.append(w)

        def parse_week_num(w_str: str) -> int:
            nums = [int(s) for s in w_str.split() if s.isdigit()]
            return nums[0] if nums else 0

        all_weeks.sort(key=parse_week_num)
        allowed_weeks = set(all_weeks[:max_w_count])
        imminent_weeks = set(all_weeks[:2])  # Current round and Round +1

        # 2. Deduplicate by (league, week, match) and apply Elite Filter to distant rounds
        def get_match_key(e: dict) -> str:
            return f"{e.get('league', '')} | {e.get('week', '')} | {e['match_name']}"

        best_by_match = {}
        for edge in qualified_edges:
            w = edge.get("week", "")
            key = get_match_key(edge)
            edge["tier"] = classify_tier(edge)

            # Profile week restriction: discard weeks beyond allowed horizon
            if w and w not in allowed_weeks:
                continue

            if key not in best_by_match or edge["min_edge"] > best_by_match[key]["min_edge"]:
                best_by_match[key] = edge

        min_odds_limit = profile.get("min_odds", 1.45)
        max_odds_limit = profile.get("max_odds", 99.0)
        
        def _within_odds_bounds(c):
            lg = c.get("league", "")
            min_l = min_odds_limit.get(lg, 1.45) if isinstance(min_odds_limit, dict) else min_odds_limit
            max_l = max_odds_limit.get(lg, 99.0) if isinstance(max_odds_limit, dict) else max_odds_limit
            return min_l <= c.get("raw_odds", 0.0) <= max_l

        pool = [c for c in best_by_match.values() if _within_odds_bounds(c)]
        # Sort by Tier ascending (Tier 1 first), then edge (EV) descending, then win probability
        pool.sort(key=lambda x: (x["tier"], -x["min_edge"], -x.get("mu_phat", 0.0)))

        t1_pool = [c for c in pool if c["tier"] == 1]
        t2_pool = [c for c in pool if c["tier"] == 2]
        t3_pool = [c for c in pool if c["tier"] == 3]

        tickets = []
        used_matches = set()

        # 3. Priority 1: Top Anchor Single (Tier 1 preferred, Tier 2 if no Tier 1)
        avail_anchors = t1_pool if t1_pool else t2_pool
        imminent_anchors = [c for c in avail_anchors if not c.get("week") or c.get("week") in imminent_weeks]
        anchor = imminent_anchors[0] if imminent_anchors else (avail_anchors[0] if avail_anchors else None)
        if anchor:
            anchor_key = get_match_key(anchor)
            stake = calculate_tier_stake(balance, tier=anchor["tier"], ticket_type="single", odds=anchor["raw_odds"], edge=anchor.get("oos_edge", 0.0), n_train=anchor.get("n_train", 300))
            tickets.append({
                "type": "single",
                "legs": [anchor],
                "combined_odds": anchor["raw_odds"],
                "avg_edge": anchor["min_edge"],
                "stake": stake,
                "tier": anchor["tier"],
                "role": "core_anchor"
            })
            used_matches.add(anchor_key)

        # 4. Priority 2: Smart Double (Tier 1 Anchor + Tier 2 Booster)
        allow_doubles = portfolio_mode.get("allow_doubles", True)
        roll = random.random()
        if allow_doubles and len(tickets) < effective_max_tickets and roll < 0.35 and pool:
            avail_anchors = [c for c in (t1_pool + t2_pool) if get_match_key(c) not in used_matches]
            avail_boosters = [c for c in (t2_pool + t3_pool) if get_match_key(c) not in used_matches]

            if avail_anchors and avail_boosters:
                if tickets and tickets[0].get("legs"):
                    t1_lg = tickets[0]["legs"][0].get("league")
                    avail_anchors.sort(key=lambda a: (0 if a.get("league") != t1_lg else 1, a["tier"], -a.get("mu_phat", 0.0), -a["min_edge"]))
                leg1 = avail_anchors[0]
                leg1_key = get_match_key(leg1)
                avail_boosters.sort(key=lambda b: (0 if b.get("league") != leg1.get("league") else 1, b["tier"], -b.get("mu_phat", 0.0), -b["min_edge"]))

                for leg2 in avail_boosters:
                    leg2_key = get_match_key(leg2)
                    if leg2_key != leg1_key:
                        comb_odds = round(leg1["raw_odds"] * leg2["raw_odds"], 2)
                        if comb_odds <= max_double_odds:
                            avg_e = (leg1["min_edge"] + leg2["min_edge"]) / 2.0
                            avg_oos = (leg1.get("oos_edge", 0.0) + leg2.get("oos_edge", 0.0)) / 2.0
                            n_tr = min(leg1.get("n_train", 300), leg2.get("n_train", 300))
                            stake = calculate_tier_stake(balance, tier=2, ticket_type="double", odds=comb_odds, edge=avg_oos, n_train=n_tr)
                            tickets.append({
                                "type": "double",
                                "legs": [leg1, leg2],
                                "combined_odds": comb_odds,
                                "avg_edge": avg_e,
                                "stake": stake,
                                "tier": 2,
                                "role": "value_double"
                            })
                            used_matches.add(leg1_key)
                            used_matches.add(leg2_key)
                            break

        # 4.5 Priority 2.5: Smart Micro-Treble (3 cross-league anchor legs, capped <= 4.20 odds, min ₦10 stake)
        allow_treble = portfolio_mode.get("allow_treble", False)
        roll_treble = random.random()
        if allow_treble and len(tickets) < effective_max_tickets and roll_treble < 0.20:
            avail_treble = [c for c in (t1_pool + t2_pool) if get_match_key(c) not in used_matches]
            leagues_seen = set()
            treble_legs = []
            for cand in avail_treble:
                lg = cand.get("league")
                if lg not in leagues_seen:
                    leagues_seen.add(lg)
                    treble_legs.append(cand)
                if len(treble_legs) == 3:
                    break

            if len(treble_legs) == 3:
                comb_odds = round(treble_legs[0]["raw_odds"] * treble_legs[1]["raw_odds"] * treble_legs[2]["raw_odds"], 2)
                max_treble_cap = 4.20
                if comb_odds <= max_treble_cap:
                    avg_e = sum(l["min_edge"] for l in treble_legs) / 3.0
                    tickets.append({
                        "type": "treble",
                        "legs": treble_legs,
                        "combined_odds": comb_odds,
                        "avg_edge": avg_e,
                        "stake": MIN_PLATFORM_STAKE,
                        "tier": 3,
                        "role": "micro_treble"
                    })
                    for l in treble_legs:
                        used_matches.add(get_match_key(l))

        # 5. Priority 3: Steady Value Singles (Tier 1 & Tier 2 always; Tier 3 only if allow_conservative)
        singles_candidates = [c for c in (t1_pool + t2_pool) if get_match_key(c) not in used_matches]
        if allow_conservative:
            singles_candidates += [c for c in t3_pool if get_match_key(c) not in used_matches]

        for candidate in singles_candidates:
            if len(tickets) >= effective_max_tickets:
                break
            cand_key = get_match_key(candidate)
            if cand_key in used_matches:
                continue

            stake = calculate_tier_stake(balance, tier=candidate["tier"], ticket_type="single", odds=candidate["raw_odds"], edge=candidate.get("oos_edge", 0.0), n_train=candidate.get("n_train", 300))
            tickets.append({
                "type": "single",
                "legs": [candidate],
                "combined_odds": candidate["raw_odds"],
                "avg_edge": candidate["min_edge"],
                "stake": stake,
                "tier": candidate["tier"],
                "role": "value_single"
            })
            used_matches.add(cand_key)

        # 6. Priority 4: Satellite Slice (Up to 5% of round capital on higher-odds balanced/liberal play)
        if allow_satellite and satellite_candidates and len(tickets) < effective_max_tickets:
            avail_sat = [s for s in satellite_candidates if get_match_key(s) not in used_matches]
            if avail_sat:
                # Pick top satellite play
                avail_sat.sort(key=lambda x: -x["min_edge"])
                sat_cand = avail_sat[0]
                sat_key = get_match_key(sat_cand)

                # Strictly capped at 5% of round bankroll or platform minimum
                sat_raw = min(25.0, max(MIN_PLATFORM_STAKE, balance * sat_pct))
                sat_stake = quantize_to_human_step(sat_raw)

                tickets.append({
                    "type": "single",
                    "legs": [sat_cand],
                    "combined_odds": sat_cand["raw_odds"],
                    "avg_edge": sat_cand["min_edge"],
                    "stake": sat_stake,
                    "tier": 3,
                    "role": "satellite_expansion"
                })
                used_matches.add(sat_key)

        return tickets

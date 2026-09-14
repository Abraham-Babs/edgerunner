import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def _load_env():
    env_path = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

_load_env()

EXCHANGE_USERNAME = os.environ.get("EXCHANGE_USERNAME", "")
EXCHANGE_PASSWORD = os.environ.get("EXCHANGE_PASSWORD", "")

SHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")
os.makedirs(SHOTS_DIR, exist_ok=True)
USER_DATA_DIR = os.path.join(ROOT_DIR, "browser_profile")
ODDS_FILE = os.path.join(ROOT_DIR, "h2h_odds.json")
CONFIRMED_EDGES_FILE = os.path.join(ROOT_DIR, "analysis", "results", "confirmed_edges.csv")
PARQUET_DIR = os.path.join(ROOT_DIR, "parquets")
BINNED_PARQUET_DIR = os.path.join(ROOT_DIR, "binned_parquets")
LOOKUP_DIR = os.path.join(ROOT_DIR, "lookup")
RESULTS_DIR = os.path.join(ROOT_DIR, "analysis", "results")
BET_LOG_FILE = os.path.join(RESULTS_DIR, "bet_log.csv")

ITEL_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15; itel A6611L Build/AP3A.240905.015.A2; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/131.0.6778.200 Mobile Safari/537.36"
)

# League configurations
LEAGUES = {
    "league_en": {
        "name": "Premier League (England)",
        "teams": 20,
        "matches_per_round": 10,
        "round_cycle_sec": 180,
        "url": "https://sports-exchange.internal/en-ng/virtuals/scheduled/leagues/premier-league",
        "lookup": "matchup_lambdas_league_en.parquet"
    },
    "league_es": {
        "name": "Primera Liga (Spain)",
        "teams": 20,
        "matches_per_round": 10,
        "round_cycle_sec": 180,
        "url": "https://sports-exchange.internal/en-ng/virtuals/scheduled/leagues/primera-liga",
        "lookup": "matchup_lambdas_league_es.parquet"
    },
    "league_it": {
        "name": "Serie League (Italy)",
        "teams": 20,
        "matches_per_round": 10,
        "round_cycle_sec": 180,
        "url": "https://sports-exchange.internal/en-ng/virtuals/scheduled/leagues/serie-league",
        "lookup": "matchup_lambdas_league_it.parquet"
    },
    "league_de": {
        "name": "Bundes League (Germany)",
        "teams": 18,
        "matches_per_round": 9,
        "round_cycle_sec": 90,
        "url": "https://sports-exchange.internal/en-ng/virtuals/scheduled/leagues/bundes-league",
        "lookup": "matchup_lambdas_league_de.parquet"
    }
}

# Statistical Edge Profiles
PROFILES = {
    "ultra_conservative": {
        "min_edge": 0.05,
        "min_win_rate": 0.60,
        "max_odds": 1.85,
        "max_concurrent_bets": 4,
        "max_weeks": 4,           # Lookahead up to 4 rounds
        "max_double_odds": 3.00
    },
    "conservative": {
        "min_edge": 0.05,
        "min_win_rate": 0.40,
        "max_odds": 99.0,
        "max_concurrent_bets": 8,
        "max_weeks": 3,
        "max_double_odds": 5.00
    },
    "balanced": {
        "min_edge": 0.04,
        "min_win_rate": 0.35,
        "max_odds": 99.0,
        "max_concurrent_bets": 10,
        "max_weeks": 4,
        "max_double_odds": 6.00
    },
    "expansive": {
        "min_edge": 0.03,
        "min_win_rate": 0.30,
        "max_odds": 99.0,
        "max_concurrent_bets": 10,
        "max_weeks": 4,
        "max_double_odds": 8.00
    }
}

# Ticket Construction Mix
TICKET_MIX_RATIOS = {
    "single": 0.65,
    "double": 0.25,
    "treble": 0.10
}

# Staking Limits & Proportions (3% - 5% of Bankroll for Sustainable Compound Growth)
MIN_PLATFORM_STAKE = 10.0
MAX_STAKE_CEILING = 500.0

DEFAULT_STAKE_PCT_LOW = 0.03   # 3% of bankroll minimum base
DEFAULT_STAKE_PCT_HIGH = 0.05  # Up to 5% of bankroll on top-tier EV

# Human Step Increments in 5s, 10s, 25s, 50s
HUMAN_STAKE_STEPS = [
    10, 15, 20, 25, 30, 35, 40, 45, 50, 
    60, 70, 75, 80, 90, 100, 125, 150, 
    175, 200, 250, 300, 400, 500
]

# Balanced Risk & Defensive Circuit Breakers
MAX_DRAWDOWN_PCT = 0.25         # If settled balance drops 25% from peak, take defensive sleep
DRAWDOWN_SLEEP_SECONDS = 900    # Sleep 15 minutes on drawdown to break variance, then resume
CONSECUTIVE_LOSS_LIMIT = 7     # Trigger cool-off after 7 losses
COOL_OFF_SECONDS = 720         # 12 minutes cool-off
PROFIT_BREATHER_GAIN = 0.50    # +50% session gain triggers a brief breather
PROFIT_BREATHER_SECONDS = 300  # 5 minutes breather

# Active Exposure Control (Pacing & Liquidity Protection)
MAX_ACTIVE_PENDING_BETS = 10   # 3/league × ~3 active leagues = ~9-10 concurrent; doubles compress slot usage
LEAGUE_MATCH_DURATION = 90     # Approximate match duration in seconds before settlement
SETTLEMENT_POLL_INTERVAL = 30  # Poll balance every 30s during cool-off/drawdown to wake up immediately
MAX_CONSECUTIVE_FAILURES = 3   # Sound noisy alert if 3 bet attempts fail consecutively





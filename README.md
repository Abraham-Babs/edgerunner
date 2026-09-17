# Automated Value Betting & Execution Engine

An algorithmic sports trading system designed for automated market discovery, statistical edge detection, deadline-aware bet execution, and strict bankroll risk management.

---

## Background & Project Context

This project originally ran as a targeted, automated value-betting bot operating on a live virtual sports platform. Its primary job was to scan high-frequency simulated football leagues, spot mispriced bookmaker odds using historical statistical models, and place qualifying value bets before match countdowns expired.

To showcase this work publicly, I anonymized and decoupled the entire codebase:
- All proprietary bookmaker domains, API endpoints, credentials, and internal category IDs were replaced with generic configuration variables.
- The raw, multi-megabyte platform odds dumps were untracked and replaced with lightweight sample fixtures.
- An offline mock mode was added so anyone can run and inspect the full pipeline without credentials, web browsers, or live network access.

What remains is the real engineering challenge: low-latency data polling, synchronization against bookmaker server clocks, automated headless browser control with anti-bot handling, dynamic bet ticket assembly, and defensive bankroll management.

---

## How It Works

The system runs in two main stages:

### 1. Market Discovery & Edge Matching
Virtual football rounds run on strict countdown clocks (usually 3 minutes per round across multiple leagues). The engine:
- Polls the active round fixtures across all supported leagues.
- Syncs its local clock with the bookmaker server's clock using HTTP response headers to calculate the exact remaining seconds before kickoff.
- Evaluates live odds against pre-compiled Poisson and empirical win-probability tables (`confirmed_edges.csv`).
- Caches any positive expected-value (+EV) bets into a shared in-memory master board.

### 2. Execution & Risk Management
When qualifying edges are found:
- **Ticket Building**: Selections are graded into tiers based on edge size and odds. The builder creates single bets or smart doubles while ensuring no match is double-counted.
- **Dynamic Staking**: Stakes are sized proportional to the edge and the current account balance (typically 2% to 5%), snapped to clean betting increments.
- **Deadline Pacing**: The runner sorts pending tickets by kickoff urgency (Earliest Deadline First) and paces clicks with natural timing jitter to avoid triggering anti-bot protections.
- **Capital Shields**: If account equity falls below 50% of the starting balance or hits a critical floor, the system terminates immediately to protect capital.

---

## Project Structure

- `engine/`
  - `runner.py`: Main execution orchestrator, event loop, and risk controls.
  - `master_board.py`: Thread-safe rolling window cache for active rounds and candidate edges.
  - `ticket_builder.py`: Builds single and multi-leg tickets with fractional bankroll sizing.
  - `bettor.py`: Handles browser navigation, slip clearing, and session API requests.
  - `parser.py`: Extracts odds from the page and clears popups or overlays.
  - `edge_matcher.py`: Cross-references live odds against pre-computed edge tables.
  - `human_interaction.py`: Generates human-like mouse paths and randomized delays.
  - `discovery/client.py`: Fast polling client with clock skew calibration.
  - `config.py`: Central settings for leagues, odds thresholds, and selectors.
- `analysis/`
  - `results/`: Historical edge data, out-of-sample test results, and logs.

---

## Quickstart

### 1. Installation
Clone the repository and set up a Python 3.11+ environment:

```bash
git clone https://github.com/your-username/sports-trading-engine.git
cd sports-trading-engine
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt  # Or: uv sync
```

### 2. Run the Offline Mock Engine (Recommended)
You can test the entire mathematical pipeline, MasterBoard synchronization, ticket builder, and simulated PnL settlements offline without needing browser binaries or credentials:

```bash
python -m engine.runner --mock --max-rounds 3
```

### 3. Run Unit Tests
Run the test suite to verify ticket construction, staking quantization, and collision guards:

```bash
python -m engine.tests.test_tickets
```

### 4. Configuration (Optional)
If configuring against a custom platform or testing environment, copy the environment template:

```bash
cp .env.example .env
```

Set your credentials and platform URL in `.env`. You can test browser automation in safe mode without placing actual bets using:

```bash
python -m engine.runner --dry-run --max-rounds 1
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

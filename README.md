# EdgeRunner

EdgeRunner started as a side project to explore how decision-making, timing, and risk controls fit together in a time-sensitive market. The goal was to build a system that could discover candidate opportunities, filter out weak signals, and enforce discipline before any execution happened.

The project combines market discovery, historical edge matching, ticket construction, bankroll controls, and execution logic. It also includes mock and dry-run modes so the decision pipeline can be tested without real exposure.

The public version has been decoupled from the original live platform and uses generic configuration and offline fixtures for review and experimentation.

## Architecture

```mermaid
flowchart LR
    A[Market Discovery] --> B[Edge Matcher]
    B --> C[Master Board]
    C --> D[Ticket Builder]
    D --> E[Risk Manager]
    E --> F{Execution Mode}

    F -->|Mock| G[Paper Settlement]
    F -->|Dry run| H[Execution Validation]
    F -->|Live adapter| I[Execution Layer]

    G --> J[Reconciliation]
    H --> J
    I --> J

    K[Historical Data] --> L[Edge Compiler]
    L --> B
```

The flow is straightforward: discover candidate markets, compare them against historical edge data, build tickets only from qualified selections, apply risk constraints, and then validate or execute the result.

## What the project does

| Area | What it does |
|---|---|
| Discovery | Polls multiple leagues and synchronizes timing |
| Edge matching | Compares current odds with historical edge tables |
| Master board | Combines candidates from different leagues and rounds |
| Ticket builder | Builds singles and multi-leg tickets |
| Risk controls | Limits exposure and aborts under defined loss conditions |
| Execution | Supports mock, dry-run, and browser-driven modes |
| Reconciliation | Matches placed tickets with settlement results |

## Quickstart

### Install dependencies

```bash
git clone https://github.com/Abraham-Babs/edgerunner.git
cd edgerunner
uv sync
```

### Run the offline mock engine

```bash
python -m engine.runner --mock --max-rounds 3
```

This exercises the mathematical pipeline, candidate selection, master-board building, and simulated settlement without requiring credentials or external connectivity.

### Run the dry-fire validation suite

```bash
python test_dry_fire_suite.py
```

This validates the DOM flow, odds selection, betslip state handling, and execution logic without placing real bets.

## Project structure

```text
engine/
├── runner.py                  # Orchestration and execution modes
├── edge_matcher.py            # Qualifies candidate edges from historical tables
├── ticket_builder.py          # Builds tickets and sizes stakes
├── master_board.py            # Aggregates and prioritizes candidates
├── bettor.py                  # Browser/API execution layer and reconciliation
├── parser.py                  # DOM parsing and page sanitization
├── human_interaction.py       # Human-like interaction timing and gestures
├── discovery/
│   └── client.py              # Market discovery and synchronization
├── pipeline/
│   └── edge_compiler.py       # Statistical compilation of confirmed edges
├── tests/
│   └── test_tickets.py        # Ticket-level verification and invariants
├── config.py                  # Profiles, risk limits, and configuration
└── ...

analysis/
├── results/
│   ├── confirmed_edges.csv
│   └── bet_log.csv
└── ...

LICENSE
README.md
sample_odds.json
```

## What I learned

The original strategy eventually stopped working. I first suspected ordinary variance, but after reviewing the historical and live behavior, I found that the underlying data-generating process had changed. The historical edge was no longer representative of the current environment.

The main lesson was that good execution and risk controls cannot compensate for a model built on invalid assumptions. A system can be well engineered and still be wrong if the assumptions behind it are no longer valid.

I kept this repository as a sanitized engineering demo of the system design, the execution logic, and that lesson rather than as a claim that the original live strategy is still valid.

## Risk controls and validation

The engine includes a few practical safeguards:

- profile-based thresholds for edge and odds bounds
- duplicate-match prevention
- active exposure limits
- stop-loss protection based on bankroll and true equity
- dry-run execution for UI validation without real risk
- settlement reconciliation and bet logging
- recovery after failed submissions or stale page state

## Scope and safety

I kept this public version as a sanitized engineering demo rather than a live system. It is meant for review, offline experimentation, and technical discussion. Any real execution path requires explicit authorization, proper environment controls, and independent validation of the assumptions behind the model.

## License

This project is licensed under the [MIT License](LICENSE).

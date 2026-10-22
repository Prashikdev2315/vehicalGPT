# VehicleGPT

Offline, on-device natural-language assistant for vehicle data (TELIPORT S4, Case Study 5).

## Quick Start

```bash
make setup    # install dependencies
make sim      # generate 28-day synthetic history + labelled events
make test     # run unit + contract tests
make lowmem   # run stack in Docker with 2 GB / 2 CPU cap
```

## Architecture

The SLM does **not** analyse data. It only:
1. Turns a question into a schema-valid tool call
2. Rewrites an evidence packet into a short answer

All statistics, trends, anomaly detection, and attribution live in deterministic code.

See [docs/VehicleGPT_PRD.md](docs/VehicleGPT_PRD.md) for full requirements.

## Layout

```
ingest/      Protocol adapters (CAN, SOME/IP, VHAL, QNX, diag, ADAS)
store/       SQLite access, retention, digests
insight/     Change-point, anomaly, contribution analysis (M2)
tools/       Typed read-only tool implementations (M2)
llm/         Planner, verbaliser, verifier (M3)
sim/         Scenario injector, synthetic history generator
eval/        Benchmark questions, runners, reports
ui/          Local web UI (M5)
docs/        PRD, schemas, ADRs
tests/       Unit + contract tests
fixtures/    Recorded test data for adapter testing
```

## Contracts (do not modify without approval)

- `docs/schema.sql` — SQLite schema
- `docs/tools.schema.json` — tool call schema
- `docs/evidence_packet.schema.json` — evidence packet schema
- `docs/signals.dbc` + `docs/signal_catalog.csv` — signal definitions

## Environment

- Python 3.11+
- Docker with `--memory=2g --cpus=2` for budget enforcement
- All benchmark results labelled "laptop, 2 GB / 2 CPU container"

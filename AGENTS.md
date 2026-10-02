# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Status

**This repository is currently documentation + planning only.** No backend (`app/`), frontend (`web/`), `requirements.txt`, or `package.json` exist yet. The only runnable code is [`scripts/preflight_demo.py`](scripts/preflight_demo.py).

## Intended Stack (from design docs)

| Layer | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI (`app/api/main.py` entry point) |
| Frontend | React + TypeScript + Vite (`web/` directory) |
| Data | Polars, DuckDB (in-memory + Parquet), NetworkX |
| Optimization | Google OR-Tools (`ortools.sat.python.cp_model`) |
| Geospatial | GeoPandas, Shapely |
| Map UI | MapLibre GL JS |
| AI explanation | IBM watsonx.ai — Granite 3.3 8B Instruct (optional, 2.5s timeout) |
| Deployment | Docker Compose |

## Commands (target state when repo is built)

```bash
# Local dev
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api.main:app --reload        # Backend on :8000
cd web && npm install && npm run dev      # Frontend on :5173

# Run all tests
python -m pytest

# Run a single test file
python -m pytest tests/path/to/test_file.py

# Run a single test by name
python -m pytest tests/path/to/test_file.py::test_function_name

# Preflight (offline demo validator — five deterministic checks)
python scripts/preflight_demo.py
python scripts/preflight_demo.py --strict   # treats WARN as failure

# Docker
cp .env.example .env
docker compose up --build

# Offline demo mode (no external credentials required)
DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false docker compose up --build
```

## Critical Design Constraints

- **Deterministic core, optional AI:** Disruption impact, route feasibility, and cold-chain classification must be deterministic and auditable. Granite/watsonx.ai explains results only — it must never generate operational decisions.
- **Offline-first:** All core logic must work with `DEMO_MODE=true WATSONX_ENABLED=false NETWORK_REQUIRED=false`. External API calls must have timeouts (2.5s for watsonx.ai) and deterministic fallbacks.
- **Configurable cold-chain policies:** Temperature thresholds and severity rules are loaded from policy dicts/profiles — never hardcoded. See `classify_excursion()` in [`scripts/preflight_demo.py`](scripts/preflight_demo.py:380).
- **Evidence links mandatory:** Every recommendation must carry `reason_codes` and source data. See the `CheckResult` / evidence record pattern in `preflight_demo.py`.
- **No secrets in repo:** API keys and credentials are loaded from environment variables or `.env` (never committed).

## Code Style (from preflight_demo.py patterns)

- `from __future__ import annotations` at top of all Python files
- Dataclasses (`@dataclass`) for structured results; avoid plain dicts for function return types
- Lazy imports inside functions for optional dependencies — degrade to `SKIP` with install hint, never crash
- Functions return `tuple[status, reason_codes, detail, evidence]` for check/classify operations
- Reason codes are `SCREAMING_SNAKE_CASE` strings (e.g., `PORT_NODE_BLOCKED`, `ETA_SLA_BREACH`)
- Cold-chain severity levels: `SAFE | OUT_OF_RANGE | EXCURSION_REVIEW | URGENT_ESCALATION | POLICY_REQUIRED`
- Preflight writes machine-readable evidence to `reports/preflight_report.json` (create `reports/` dir via `mkdir -p`)

## Key API Endpoints (planned)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/disruptions/activate` | Activate a disruption scenario |
| GET | `/api/v1/shipments/{shipment_id}` | Shipment detail + alternatives |
| GET | `/api/v1/assets/idle` | Idle compatible assets |
| GET | `/api/v1/cold-chain/{shipment_id}/timeline` | Sensor timeline + excursion events |
| POST | `/api/v1/explanations/generate` | Granite explanation for a decision |
| POST | `/api/v1/action-plan/export` | Export action plan (JSON or Markdown) |

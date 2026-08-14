<h1 align="center">🏥 ICU Vitals Transformer</h1>
<p align="center"><b>Hexagonal Skill Engine for Real-Time ICU Patient Monitoring</b></p>

<p align="center"><sub>FastAPI · Pydantic v2 · MCP · Prometheus · Docker · pytest</sub></p>

<p align="center">
  <img src="https://img.shields.io/badge/status-production--ready-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/Version-v0.9.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.111+-teal?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Pydantic_v2-2.7+-purple?logo=pydantic" alt="Pydantic">
  <img src="https://img.shields.io/badge/MCP-1.0+-black?logo=modelcontextprotocol" alt="MCP">
  <img src="https://img.shields.io/badge/A2A-Agent2Agent-blue" alt="A2A">
  <img src="https://img.shields.io/badge/Prometheus-0.20+-orange?logo=prometheus" alt="Prometheus">
  <img src="https://img.shields.io/badge/Docker-Ready-blue?logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/Tests-272%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/Coverage-94%25-green" alt="Coverage">
  <img src="https://img.shields.io/badge/CI-4%20gates%20green-brightgreen" alt="CI">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT">
</p>

---

FHIR R4 vital sign ingestion → deterministic multi-horizon deterioration forecast → NEWS2-inspired severity classification, exposed as composable **MCP** and **A2A (Agent-to-Agent)** tools.

---

## 📋 Table of Contents

- [Clinical Safety Disclaimer](#-clinical-safety-disclaimer)
- [What This Is](#-what-this-is)
- [What This Is Not](#-what-this-is-not)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [API Reference](#-api-reference)
- [MCP Tools](#-mcp-tools)
- [A2A (Agent-to-Agent)](#-a2a-agent-to-agent)
- [Pluggable Backends](#-pluggable-backends)
- [Configuration](#-configuration)
- [Testing](#-testing)
- [License](#-license)

---

> **⚠️ CLINICAL SAFETY DISCLAIMER**
>
> This software is **NOT a medical device**. It is **NOT FDA or CE marked** for clinical use.
>
> All forecasts and deterioration scores are **informational only** and **must be reviewed by a qualified clinician** before any clinical action. Do **not** use this tool for:
> - Autonomous triage or diagnosis
> - Closed-loop intervention or alerting
> - Replacement of clinical judgment
>
> The models are **deterministic scoring tools** — they have no understanding of patient context, comorbidities, medications, or treatment plans. Any clinical deployment **must** include human-in-the-loop oversight, validation against local patient populations, and appropriate governance.

## What This Is

A **reusable, deterministic clinical tool** — not an autonomous agent. It ingests FHIR R4 vital signs, generates deterioration forecasts using deterministic trend extrapolation, and returns severity-classified predictions via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) and the [A2A (Agent-to-Agent)](https://github.com/google/A2A) protocol.

Designed to be composed into larger clinical agent architectures. The tool makes predictions; the caller decides what to do with them.

## What This Is Not

- **Not an autonomous agent** — no self-directed alerting, escalation, or closed-loop action
- **Not a monitoring dashboard** — no UI, no real-time charts
- **Not a replacement for clinical judgment** — deterministic scoring only, no diagnostic claims

## Architecture

`icu-vitals-transformer` v0.9.0 is a **Hexagonal Skill Engine**: the clinical
logic (trend extrapolation, DDS, FHIR windowing, episode lifecycle, SafetyShell)
lives in a pure-Python core (`src/core/`) that depends only on the standard
library + Pydantic. Adapters handle REST v2, MCP, A2A, Redis/memory storage,
Prometheus observability, and CIMD/JWT auth at the outer rings.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/SAFETY.md`](docs/SAFETY.md), and [`docs/MIGRATION.md`](docs/MIGRATION.md).

### Inward Dependency Rule (Hexagonal Core Isolation)

**`src/core/` and `src/ports/` MUST remain 100 % pure Python** — they import
none of `fastapi`, `mcp`, `prometheus_client`, `redis`, or `numpy`. This is
enforced as a CI gate:

```bash
! grep -rnE 'import (fastapi|mcp|prometheus_client|redis|numpy)' src/core/ src/ports/
```

| Layer | Path | Responsibility |
|-------|------|----------------|
| **Core Domain** | `src/core/domain/*` | Pure Pydantic v2 vital/episode/forecast/assessment contracts |
| **Core Engines** | `src/core/{forecasting,governance,ingestion,windowing,services,safety}` | Deterministic trend extrapolation, DDS, FHIR parsing, episode FSM, SafetyShell |
| **Driven Ports** | `src/ports/*.py` | `VitalsRepository`, `EpisodeRepository`, `AssessmentRepository`, `ForecastBackend` protocols |
| **Driving Adapters** | `src/adapters/{rest,mcp,a2a}` | REST v2, FastMCP (stdio/http), A2A, observability, CIMD auth |
| **Driven Adapters** | `src/adapters/storage/*` | In-memory (dev) and Redis (multi-replica) repository impls |
| **Observability** | `src/observability/*` | Label-free Prometheus metrics + JSON structured logging |

## Tech Stack

- **Python 3.12** + FastAPI + Pydantic v2
- **Deterministic trend extrapolation** — linear forecasting with clinical uncertainty bounds, enforced by `SafetyShell`
- **Pluggable backends** — `ForecastBackend` protocol allows alternative implementations (neural, API-based)
- **Pluggable repositories** — `VitalsRepository`/`EpisodeRepository` ports allow in-memory (dev) or Redis (multi-replica) storage
- **MCP 1.0+** — stdio and Streamable-HTTP transports
- **A2A** — Agent-to-Agent task & discovery facade
- **Prometheus** — observability metrics
- **CIMD/JWT** — bearer-token principal extraction for audit

## Quick Start

```bash
git clone https://github.com/aragit/icu-vitals-transformer.git
cd icu-vitals-transformer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run REST API (default)
uvicorn src.main:app --reload --port 8001

# Run as MCP Streamable HTTP server (production transport)
MCP_TRANSPORT=http python -m src.mcp_server.server

# Run as MCP stdio server (local dev / agent orchestrators)
MCP_TRANSPORT=stdio python -m src.mcp_server.stdio

# Run with Docker
docker compose -f docker/docker-compose.yml up --build
```

### Server configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `icu-vitals-transformer` | Application name |
| `APP_VERSION` | `0.9.0` | Application version |
| `DEBUG` | `false` | Enable debug logging |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `FORECAST_HORIZONS` | `[60, 240, 720]` | Forecast horizons in minutes |
| `MCP_SERVER_NAME` | `icu-vitals-transformer` | MCP server name |
| `MCP_TRANSPORT` | `stdio` | MCP transport: `stdio` (dev) or `http` (Streamable HTTP) |
| `REPOSITORY_BACKEND` | `memory` | Storage backend: `memory` (dev) or `redis` (multi-replica) |
| `A2A_ENABLED` | `false` | Enable the A2A facade (`GET /.well-known/agent.json`, `POST /a2a/tasks`) |

## API Reference

### `POST /v2/vitals/ingest`

Ingest FHIR R4 Observations; auto-resolve or create the active clinical episode.

```bash
curl -X POST http://localhost:8001/v2/vitals/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "PT-001",
    "observations": [
      {"resourceType": "Observation", "subject": {"reference": "Patient/PT-001"},
       "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
       "valueQuantity": {"value": 72, "unit": "bpm"},
       "effectiveDateTime": "2026-07-02T08:00:00Z"}
    ]
  }'
```

### `GET /v2/episodes/{episode_id}/current` · `/forecast` · `/deterioration` · `/discovery`

Retrieve the latest windowed vitals, a SafetyShell-bounded forecast, the DDS
deterioration index, or the active vital channels for an episode.

### `GET /discover`

Capability-negotiation manifest (protocols, tools, resources, safety bounds).

```bash
curl http://localhost:8001/discover
```

### Legacy `GET /vitals/*` routes

Backward-compatible v1 endpoints (auto-create episodes, `_meta` envelope). Return `Deprecation: true` with a `Link: </v2/vitals/ingest>; rel="alternate"` header. **Error handling**: invalid/unrecognised FHIR Observations are silently skipped with a warning-level log; unrecognised channels are `null` and DDS is computed only over available values. Missing data does **not** raise.

### `GET /health/liveness` and `GET /health/readiness`

Liveness and readiness probes.

### `GET /metrics`

Prometheus metrics endpoint.

## MCP Tools

The server exposes tools via the Model Context Protocol:

| Tool | Transport | Description |
|------|-----------|-------------|
| `ingest_vitals` | stdio / http / A2A | Accepts FHIR R4 Observation dicts, returns windowed vital signs |
| `get_forecast` | stdio / http / A2A | Returns multi-horizon forecast (default 1h, accepts `horizon_minutes`) |
| `get_deterioration_index` | stdio / http / A2A | Computes ensemble deterioration index with severity classification |
| `discover_episode` | stdio / http | Resolves the active episode(s) for a patient |

Connect via stdio for local agent orchestrators, or Streamable HTTP
(`MCP_TRANSPORT=http`, endpoint `http://localhost:8000/mcp`) for multi-agent
orchestrators.

## A2A (Agent-to-Agent)

`icu-vitals-transformer` is an [A2A](https://github.com/google/A2A)-capable
agent, feature-flagged behind **`A2A_ENABLED=true`**:

- `GET /.well-known/agent.json` — the A2A agent card (negotiation manifest).
- `POST /a2a/tasks` — execute a task (`action` ∈ `ingest_vitals`,
  `get_forecast`, `get_deterioration_index`); returns a standard A2A
  Artifact whose `data` part carries the clinical result + the `_meta` safety
  envelope.

```bash
A2A_ENABLED=true uvicorn src.main:app --reload --port 8001

# Discover capabilities
curl http://localhost:8001/.well-known/agent.json

# Ingest via A2A
curl -X POST http://localhost:8001/a2a/tasks \
  -H "Content-Type: application/json" \
  -d '{"id":"t1","message":{"role":"user","parts":[{"kind":"data","data":{
       "action":"ingest_vitals",
       "parameters":{"patient_id":"PT-001","observations":[...]}}}]}}'
```

When `A2A_ENABLED=false` (default), both A2A routes return **404** and the REST
v2 / MCP surfaces are unaffected.

## Pluggable Backends & Repositories

The `ForecastBackend` protocol (`src/ports/forecaster.py`) lets you swap
forecasting strategies without touching the ensemble or governance layers.
Likewise, `src/ports/repository.py` defines `VitalsRepository`,
`EpisodeRepository`, and `AssessmentRepository` ports, with in-memory (dev) and
Redis (multi-replica) implementations selectable via `REPOSITORY_BACKEND`.

```python
from src.ports.forecaster import ForecastBackend

class MyCustomBackend:
    def forecast(self, current_window, horizon_minutes, trend_per_hour=None):
        # Return a ForecastResult
        ...
```

### Why DeterministicBackend is the default

- **Reproducibility** — the same input always yields the identical forecast, critical for audit and debugging
- **Explainability** — forecast changes trace to slope/intercept values, not hidden weights
- **Zero GPU dependency** — CPU-only with predictable latency
- **MCP tool contract** — stateless, deterministic, and reusable makes the tool safe to compose into larger orchestration pipelines without surprises

## Configuration

Settings are loaded via Pydantic Settings from environment variables or a `.env` file (see the consolidated table in [Quick Start](#-quick-start)).

## Testing

```bash
pytest -v --cov=src --cov-report=term-missing --cov-fail-under=92   # modernization gate
```

> **CI gate**: `.github/workflows/ci.yml` enforces Ruff, Mypy, zero framework imports in `src/core` + `src/ports`, and ≥ 92 % coverage. See [`docs/MIGRATION.md`](docs/MIGRATION.md).

## License

MIT

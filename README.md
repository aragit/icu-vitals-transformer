<h1 align="center">🏥 ICU Vitals Transformer</h1>
<p align="center">
  <b>Hexagonal Skill Engine — Deterministic Clinical Forecasting via MCP & A2A</b>
</p>
<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/status-production--ready-brightgreen" alt="Status"></a>
  <a href="#"><img src="https://img.shields.io/badge/Version-v0.9.1-blue" alt="Version"></a>
  <a href="#"><img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python" alt="Python"></a>
  <a href="#"><img src="https://img.shields.io/badge/FastAPI-0.111+-teal?logo=fastapi" alt="FastAPI"></a>
  <a href="#"><img src="https://img.shields.io/badge/Pydantic_v2-2.7+-purple?logo=pydantic" alt="Pydantic"></a>
  <a href="#"><img src="https://img.shields.io/badge/MCP-2026--07--28-black?logo=modelcontextprotocol" alt="MCP"></a>
  <a href="#"><img src="https://img.shields.io/badge/A2A-Agent2Agent-blue" alt="A2A"></a>
  <a href="#"><img src="https://img.shields.io/badge/Prometheus-0.20+-orange?logo=prometheus" alt="Prometheus"></a>
  <a href="#"><img src="https://img.shields.io/badge/Docker-Ready-blue?logo=docker" alt="Docker"></a>
  <a href="#"><img src="https://img.shields.io/badge/Tests-342%20passing-brightgreen" alt="Tests"></a>
  <a href="#"><img src="https://img.shields.io/badge/Coverage-94.57%25-green" alt="Coverage"></a>
  <a href="#"><img src="https://img.shields.io/badge/CI-4%20gates%20green-brightgreen" alt="CI"></a>
  <a href="#"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT"></a>
</p>

FHIR R4 vital sign ingestion → deterministic multi-horizon trend extrapolation → DDS (Deterministic Deterioration Score) severity classification, exposed as composable MCP and A2A skill surfaces. Every forecast passes through a SafetyShell invariant gate that clamps physiological bounds, surfaces stale-data warnings, and fails closed.

---

## 📋 Table of Contents

- [Clinical Safety Disclaimer](#-clinical-safety-disclaimer)
- [What This Is](#-what-this-is)
- [What This Is Not](#-what-this-is-not)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [DDS Severity Tiers](#-dds-severity-tiers)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [API Reference](#-api-reference)
- [MCP Tools](#-mcp-tools)
- [A2A (Agent-to-Agent) Facade](#-a2a-agent-to-agent-facade)
- [Observability](#-observability)
- [Testing](#-testing)
- [Architecture Decisions](#-architecture-decisions)
- [Contributing](#-contributing)
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

A reusable, deterministic clinical micro-skill — not an autonomous agent. It ingests FHIR R4 vital signs, generates deterioration forecasts using least-squares trend extrapolation with clinical uncertainty bounds, and returns DDS (Deterministic Deterioration Score) severity classifications via the Model Context Protocol (MCP) and an optional A2A (Agent-to-Agent) facade.

Designed to be composed into larger clinical agent architectures (e.g., AXIOMIS, SentriXIA). The skill makes predictions; the orchestrator decides what to do with them.

## What This Is Not

- **Not an autonomous agent** — no self-directed alerting, escalation, or closed-loop action
- **Not a monitoring dashboard** — no UI, no real-time charts
- **Not a replacement for clinical judgment** — deterministic scoring only, no diagnostic claims
- **Not a neural model** — zero GPU dependency; forecasts are linear extrapolation with explicit uncertainty

## Key Features

| Capability | Detail |
|---|---|
| FHIR R4 Ingestion | LOINC-coded vital signs (HR, BP, SpO₂, RR, Temp, AVPU) with unit validation (°C, mmHg, %, bpm, /min) |
| AVPU Support | Alert / Voice / Pain / Unresponsive via valueQuantity, valueString, or valueCodeableConcept (SNOMED CT) |
| Temporal Windowing | 5-minute sliding windows anchored to the most recent observation; handles out-of-order messages |
| Trend Extrapolation | Pure-Python least-squares slope estimation over historical windows; falls back to flat-line when < 2 windows |
| SafetyShell | Invariant gate: physiological bound clamping, stale-data warning (> 300 s), fail-closed fallback on exception |
| DDS Scoring | Deterministic Deterioration Score (0–20) with explicit contributing factors; severity mapped to episode state |
| Episode FSM | Episode lifecycle tracking (NORMAL → WARNING → ALERT → EMERGENCY) with deterministic transitions |
| Multi-Transport | MCP (stdio / Streamable HTTP), REST v2, A2A facade |
| Pluggable Storage | In-memory (dev) or Redis (multi-replica, sorted-set time series, 30-day TTL) |
| Observability | Label-free Prometheus metrics + structured JSON logging with correlation IDs |
| Protocol Manifests | mcp.json, SKILL.md, AGENT_CARD.json for capability negotiation |

## Architecture

`icu-vitals-transformer` is a **Hexagonal Skill Engine**: clinical logic lives in a pure-Python core (`src/core/`) that depends only on the standard library + Pydantic. Adapters handle REST v2, MCP, A2A, Redis/memory storage, Prometheus observability, and CIMD/JWT auth at the outer rings.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/SAFETY.md`](docs/SAFETY.md), and [`docs/MIGRATION.md`](docs/MIGRATION.md).

### Inward Dependency Rule (Hexagonal Core Isolation)

**`src/core/` and `src/ports/` MUST remain 100 % pure Python** — they import none of `fastapi`, `mcp`, `prometheus_client`, `redis`, or `numpy`. This is enforced as a CI gate:

```bash
! grep -rnE 'import (fastapi|mcp|prometheus_client|redis|numpy)' src/core/ src/ports/
```

| Layer | Path | Responsibility |
|-------|------|----------------|
| **Core Domain** | `src/core/domain/*` | Pure Pydantic v2 vital/episode/forecast/assessment contracts |
| **Core Engines** | `src/core/{forecasting,governance,ingestion,windowing,services,safety}` | Deterministic trend extrapolation, DDS, FHIR parsing, episode FSM, SafetyShell |
| **Driven Ports** | `src/ports/*.py` | VitalRepository, EpisodeRepository, AssessmentRepository, ForecastBackend protocols |
| **Driving Adapters** | `src/adapters/{rest,mcp,a2a}` | REST v2, FastMCP (stdio/http), A2A, observability, CIMD auth |
| **Driven Adapters** | `src/adapters/storage/*` | In-memory (dev) and Redis (multi-replica) repository impls |
| **Observability** | `src/observability/*` | Label-free Prometheus metrics + JSON structured logging |

### SafetyShell Invariant Gate

Every forecast output passes through the SafetyShell before reaching any adapter:

```
input: window + trend_per_hour
   │
   ├─ try   → ForecastBackend.forecast()  (deterministic trend extrapolation)
   └─ except → SafetyShell flat-line fallback  (never leaks inner failure)
   ↓
   clamp projected window to physiological BOUNDS
   enforce lower <= forecasted <= upper per channel
   raise stale_data_warning (>300s)
```

The shell is constructed in `src/dependencies.py` with optional `on_fallback` and `on_stale_data` hooks that increment the `safety_shell_fallback_total` and `stale_data_warning_total` counters — core stays framework-free; the Prometheus hooks are wired at the adapter boundary.

## DDS Severity Tiers

The Deterministic Deterioration Score (DDS) is a bounded composite (0–20) computed from vital sign deviations. It is not NEWS2 — it is a simplified, deterministic variant designed for agentic tool consumption.

| Tier | DDS Range | Clinical Meaning | Episode State |
|------|-----------|------------------|---------------|
| NORMAL | 0 – 2 | No immediate physiological concern | NORMAL |
| WARNING | 3 – 4 | Mild derangement; trend monitoring warranted | WARNING |
| ALERT | 5 – 6 | Significant physiology drift; escalate review | ALERT |
| EMERGENCY | ≥ 7 | Critical thresholds exceeded; treat as urgent | EMERGENCY |

AVPU = Unresponsive automatically scores +3 (altered consciousness). Trend persistence modifiers may add +1 when the episode state is TRENDING_NEGATIVE (R2.1+).

## Tech Stack

- **Python 3.12** + FastAPI + Pydantic v2
- **Deterministic trend extrapolation** — linear forecasting with clinical uncertainty bounds, enforced by SafetyShell
- **Pluggable backends** — ForecastBackend protocol allows alternative implementations (neural, API-based)
- **Pluggable repositories** — VitalsRepository/EpisodeRepository ports allow in-memory (dev) or Redis (multi-replica) storage
- **MCP 2026-07-28** — stdio and Streamable HTTP transports; capability negotiation; discover_capabilities tool
- **A2A** — Agent-to-Agent task & discovery facade (feature-flagged)
- **Prometheus** — label-free observability metrics (no patient_id/episode_id labels)
- **CIMD/JWT** — bearer-token principal extraction for audit trails

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
MCP_TRANSPORT=http uvicorn src.main:app --reload --port 8001

# Run as MCP stdio server (local dev / agent orchestrators)
MCP_TRANSPORT=stdio python -m src.adapters.mcp.server

# Run with Docker
docker compose -f docker/docker-compose.yml up --build
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `icu-vitals-transformer` | Application name |
| `APP_VERSION` | `from package metadata` | Application version (read dynamically) |
| `DEBUG` | `false` | Enable debug logging |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `FORECAST_HORIZONS` | `[60, 240, 720]` | Forecast horizons in minutes (1h, 4h, 12h) |
| `MCP_SERVER_NAME` | `icu-vitals-transformer` | MCP server name |
| `MCP_TRANSPORT` | `stdio` | MCP transport: `stdio (dev) or http (Streamable HTTP) |
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
      {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/PT-001"},
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "valueQuantity": {"value": 72, "unit": "bpm"},
        "effectiveDateTime": "2026-07-02T08:00:00Z"
      }
    ]
  }'
```

### `GET /v2/episodes/{episode_id}/current` · `/forecast` · `/deterioration` · `/discovery`

Retrieve the latest windowed vitals, a SafetyShell-bounded forecast, the DDS deterioration index, or the active vital channels for an episode.

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

Prometheus metrics endpoint (label-free, no patient identifiers).

## MCP Tools

The server exposes tools via the Model Context Protocol:

| Tool | Description |
|------|-------------|
| `ingest_vitals` | Accepts FHIR R4 Observation dicts, returns windowed vital signs + episode ID |
| `get_forecast` | Returns multi-horizon forecast (default 1h; accepts `horizon_minutes`) |
| `get_deterioration_index` | Computes ensemble DDS with severity classification |
| `discover_episode` | Resolves the active episode(s) for a patient |
| `discover_capabilities` | Returns the server capability matrix (tools, resources, safety bounds) |

Connect via stdio for local agent orchestrators, or Streamable HTTP (`MCP_TRANSPORT=http`, endpoint `http://localhost:8000/mcp`) for multi-agent orchestrators.

### MCP Tool Example

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command="python",
    args=["-m", "src.adapters.mcp.server"],
    env={"MCP_TRANSPORT": "stdio"}
)

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("get_deterioration_index", {
            "episode_id": "E-PT-001"
        })
```

## A2A (Agent-to-Agent) Facade

`icu-vitals-transformer` exposes an A2A skill facade (not a full agent), feature-flagged behind `A2A_ENABLED=true`:

- `GET /.well-known/agent.json` — dynamically generated A2A Agent Card from `settings.host`/`settings.port`.
- `POST /a2a/tasks` — execute a task (action ∈ `ingest_vitals`, `get_forecast`, `get_deterioration_index`); returns a standard A2A Artifact whose `data` part carries the clinical result + the `_meta` safety envelope.

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

When `A2A_ENABLED=false` (default), both A2A routes return **404** and the REST v2 / MCP surfaces are unaffected.

## Observability

### Metrics (Prometheus)

All metrics are label-free to prevent high-cardinality issues with patient identifiers in production.

| Metric | Type | Description |
|--------|------|-------------|
| `vitals_ingested_total` | Counter | Total FHIR observations ingested |
| `forecasts_generated_total` | Counter | Total forecasts generated |
| `assessments_total` | Counter | Total DDS assessments computed |
| `forecast_latency_seconds` | Histogram | Per-horizon forecast latency |
| `forecast_duration_seconds` | Histogram | Ensemble forecast service latency |
| `ingest_duration_seconds` | Histogram | Ingest + windowing service latency |
| `trend_computation_latency_seconds` | Histogram | Least-squares trend computation latency |
| `safety_shell_fallback_total` | Counter | SafetyShell exception fallbacks |
| `stale_data_warning_total` | Counter | Stale-data warnings triggered |
| `episode_state` | Gauge | Episode count per state (NORMAL, WARNING, ALERT, EMERGENCY, CRITICAL) |

### Structured Logging

JSON-formatted logs with correlation IDs, patient_id, episode_id, and tool_name for distributed tracing.

```json
{
  "timestamp": "2026-08-15T10:30:00Z",
  "level": "INFO",
  "message": "Forecast generated",
  "correlation_id": "abc-123",
  "episode_id": "E-PT-001",
  "patient_id": "PT-001",
  "tool_name": "get_forecast",
  "deterioration_index": 4,
  "severity": "WARNING"
}
```

## Testing

```bash
pytest -v --cov=src --cov-report=term-missing --cov-fail-under=92
```

**CI gate**: `.github/workflows/ci.yml` enforces Ruff, Mypy, zero framework imports in `src/core` + `src/ports`, and ≥ 92 % coverage. See [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Architecture Decisions

See [`docs/ADR-001-episode-id-format.md`](docs/ADR-001-episode-id-format.md) for the decision to retain deterministic `E-{patient_id}` episode IDs in v0.9.x.

## Contributing

Fork the repository → Create a feature branch (`git checkout -b feature/my-fix`) → Ensure all CI gates pass locally:

```bash
ruff check src/ tests/
mypy src/core/ src/ports/
pytest --cov=src --cov-fail-under=92
```

Commit with clear messages (`fix(clinical): ...`, `feat(adapter): ...`, `docs: ...`) → Open a pull request.

**Core isolation is mandatory.** Any PR that introduces `fastapi`, `mcp`, `prometheus_client`, `redis`, or `numpy` imports into `src/core/` or `src/ports/` will be rejected by CI.

## License

MIT

<h1 align="center">🏥 ICU Vitals Transformer</h1>
<p align="center"><b>MCP Clinical Forecasting Skill for Real-Time ICU Patient Monitoring</b></p>

<p align="center"><sub>FastAPI · Pydantic v2 · MCP · Prometheus · Docker · pytest</sub></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.111+-teal?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Pydantic_v2-2.7+-purple?logo=pydantic" alt="Pydantic">
  <img src="https://img.shields.io/badge/MCP-1.0+-black?logo=modelcontextprotocol" alt="MCP">
  <img src="https://img.shields.io/badge/Prometheus-0.20+-orange?logo=prometheus" alt="Prometheus">
  <img src="https://img.shields.io/badge/Docker-Ready-blue?logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT">
</p>

---

FHIR R4 vital sign ingestion → deterministic multi-horizon deterioration forecast → NEWS2-inspired severity classification, exposed as composable MCP tools.

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

A **reusable, deterministic clinical tool** — not an agent. It ingests FHIR R4 vital signs, generates deterioration forecasts using deterministic trend extrapolation, and returns severity-classified predictions via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

Designed to be composed into larger clinical agent architectures. The tool makes predictions; the caller decides what to do with them.

## What This Is Not

- **Not an autonomous agent** — no self-directed alerting, escalation, or closed-loop action
- **Not a monitoring dashboard** — no UI, no real-time charts
- **Not a replacement for clinical judgment** — deterministic scoring only, no diagnostic claims

## Architecture

| Layer | Responsibility |
|-------|---------------|
| **Ingestion** | Parse FHIR R4 Observation resources (LOINC-coded) |
| **Windowing** | 5-minute sliding window aggregation |
| **Forecasting** | Multi-horizon prediction (1h, 4h, 12h) via pluggable backends (default: deterministic trend extrapolation) |
| **Governance** | NEWS2-inspired deterioration index + deterministic severity classification |
| **MCP Server** | Exposes ingest_vitals, get_forecast, get_deterioration_index tools |

## Tech Stack

- **Python 3.12** + FastAPI + Pydantic v2
- **Deterministic trend extrapolation** — linear forecasting with clinical uncertainty bounds
- **Pluggable backends** — `ForecastBackend` protocol allows alternative implementations (neural, API-based)
- **Prometheus** — observability metrics
- **MCP** — Model Context Protocol for tool interoperability

## Quick Start

```bash
git clone https://github.com/aragit/icu-vitals-transformer.git
cd icu-vitals-transformer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run as FastAPI server
uvicorn src.main:app --reload --port 8001

# Run as MCP stdio server (for agent orchestrators)
python -m src.mcp_server.stdio

# Run with Docker
docker compose -f docker/docker-compose.yml up --build
```

## API Reference

### `POST /vitals/ingest`

Ingest FHIR R4 Observations and return windowed vital signs.

```bash
curl -X POST http://localhost:8001/vitals/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "observations": [
      {
        "resourceType": "Observation",
        "subject": {"reference": "Patient/PT-001"},
        "code": {
          "coding": [
            {"system": "http://loinc.org", "code": "8867-4"}
          ]
        },
        "valueQuantity": {"value": 72, "unit": "bpm"},
        "effectiveDateTime": "2026-07-02T08:00:00Z"
      }
    ]
  }'
```

### `GET /vitals/current/{patient_id}`

Get the latest windowed vitals for a patient.

```bash
curl http://localhost:8001/vitals/current/PT-001
```

### `GET /vitals/forecast/{patient_id}`

Generate multi-horizon forecasts (1h, 4h, 12h) for a patient.

```bash
curl http://localhost:8001/vitals/forecast/PT-001
```

### `GET /vitals/deterioration/{patient_id}`

Compute ensemble deterioration index and severity classification.

```bash
curl http://localhost:8001/vitals/deterioration/PT-001
```

### `GET /health/` and `GET /health/ready`

Liveness and readiness probes.

### `GET /metrics/`

Prometheus metrics endpoint.

> **Error handling**: Invalid or unrecognised FHIR Observation resources are silently skipped with a warning-level log entry — ingestion continues without aborting. Forecast results use `null` for any vital sign not present in the input window, and the deterioration index is computed only from available values. Missing data does not produce an exception.

## MCP Tools

The server exposes three tools via the Model Context Protocol:

| Tool | Description |
|------|-------------|
| `ingest_vitals` | Accepts FHIR R4 Observation dicts, returns windowed vital signs |
| `get_forecast` | Returns multi-horizon forecast for a patient (default 1h, accepts `horizon_minutes`) |
| `get_deterioration_index` | Computes ensemble deterioration index with severity classification |

Use the MCP stdio transport to connect from any MCP-compatible agent orchestrator:

```python
# Agent-side example (pseudo-code)
response = await mcp_client.call_tool("ingest_vitals", {
    "patient_id": "PT-001",
    "observations": [fhir_observation_dict]
})
window = response[0].text  # JSON VitalSignsWindow
```

## Pluggable Backends

The `ForecastBackend` protocol in `src/forecasting/backends.py` allows swapping forecasting strategies without modifying the ensemble or governance layers.

```python
from src.forecasting.backends import DeterministicBackend, ForecastBackend

class MyCustomBackend:
    def forecast(self, current_window, horizon_minutes, trend_per_hour=None):
        # Return a ForecastResult
        ...

results = ensemble_forecast(window, backend=MyCustomBackend())
```

### Why DeterministicBackend is the default

- **Reproducibility** — the same input always produces the identical forecast, critical for audit and debugging
- **Explainability** — forecast changes are traceable to slope and intercept values, not hidden weights
- **Zero GPU dependency** — runs on CPU-only hardware with predictable latency
- **MCP tool contract** — stateless, deterministic, and reusable makes the tool safe to compose into larger orchestration pipelines without surprises

Neural or API-based backends (e.g., Chronos-2, vLLM, OpenAI) can be implemented as alternative backends but are **opt-in only** and require additional governance considerations.

## Configuration

Settings are loaded via Pydantic Settings from environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `icu-vitals-transformer` | Application name |
| `APP_VERSION` | `0.1.0` | Application version |
| `DEBUG` | `false` | Enable debug logging |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `FORECAST_HORIZONS` | `[60, 240, 720]` | Forecast horizons in minutes |
| `MCP_SERVER_NAME` | `icu-vitals-transformer` | MCP server name |
| `MCP_TRANSPORT` | `stdio` | MCP transport (`stdio` or `sse`) |

## Testing

```bash
pytest -v --cov=src
```

## License

MIT

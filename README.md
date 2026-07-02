# MCP clinical forecasting skill for real-time ICU patient monitoring.

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
uvicorn src.main:app --reload --port 8001
```
**License**

MIT
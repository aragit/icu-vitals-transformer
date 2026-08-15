# Architecture — ICU Vitals Transformer (v0.2.0 Reference Architecture)

This document describes the v0.2.0 Hexagonal / Onion reference architecture for
`icu-vitals-transformer`: a deterministic ICU vital-sign forecasting skill.

## 4.1 C4 / Layer Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DRIVING ADAPTERS (transports)        src/adapters/{rest,mcp,storage}    │
│  REST v2 routes   │  FastMCP tools   │  Prometheus observability           │
│  GET /discover    │  Streamable HTTP │  Observability (metrics + logs)    │
└──────────▲───────────────┬───────────────────▲──────────────────────────┘
           │ Depends     │ Depends           │ Depends
┌──────────┴───────────────┴───────────────────┴──────────┐
│  CORE APPLICATION (hexagonal)  src/core/  (pure Py3.12)  │
│  services.clinical_assessment  orchestration             │
│  forecasting.forecaster        trend extrapolation       │
│  forecasting.trends            least-squares slopes      │
│  governance.deterioration       DDS / severity           │
│  governance.severity            tier mapping             │
│  ingestion.fhir_parser /      FHIR parse + windowing    │
│  domain.*                      VitalSignsWindow/Episode  │
└──────────▲───────────────┬───────────────────▲──────────┘
           │ implements    │ implements        │ driven
┌──────────┴───────────────┴───────────────────┴──────────┐
│  DRIVEN ADAPTERS (ports)    src/ports/ + src/adapters/   │
│  repository.Protocol         Vitals/Episode/Assessment     │
│  forecaster.Protocol         ForecastBackend contract     │
│  Memory (dev) / Redis         multi-replica storage      │
│  Observability               metrics + structured logging  │
└───────────────────────────────────────────────────────────┘
```

### Layer responsibilities

| Layer | Path | Responsibility |
|-------|------|----------------|
| **Core Domain** | `src/core/domain/*` | Pure Pydantic v2 vital/episode/forecast/assessment contracts. Zero framework deps. |
| **Core Engines** | `src/core/{forecasting,governance,ingestion,windowing,services,safety}` | Deterministic trend extrapolation, DDS, FHIR parsing, episode FSM, SafetyShell. |
| **Driven Ports** | `src/ports/*.py` | Abstract protocols (`VitalsRepository`, `EpisodeRepository`, `ForecastBackend`). |
| **Driving Adapters** | `src/adapters/rest`, `src/adapters/mcp` | REST v2, FastMCP (stdio/http/streamable-http), observability HTTP. |
| **Driven Adapters** | `src/adapters/storage/*` | In-memory (dev) and Redis (multi-replica production) repository impls. |
| **Observability** | `src/observability/*` | Label-free Prometheus metrics + JSON structured logging. |
| **Auth** | `src/auth/*` | CIMD/JWT bearer-token principal extraction (adapter-bound). |
| **Protocols** | `manifests/*` | `mcp.json`, `SKILL.md` — discoverable capability surface. |

## 4.2 Hexagonal Inward Dependency Rule

**`src/core/` and `src/ports/` are the dependency-inversion root and MUST
remain 100 % pure Python.** Enforcement is verified in CI:

```bash
# Must return no matches:
grep -rnE '^\s*(import|from) (fastapi|mcp|prometheus_client|redis|numpy)' src/core/ src/ports/
```

- The hex core imports only the standard library + Pydantic.
- Adapters (`src/adapters/`, `src/observability/`, `src/auth/`) depend *inward*
  on `src/core/` and `src/ports/` only.
- No downward arrow from Core to Adapters.

## 4.3 Repository Selection (Dev / Production)

`src/dependencies.py` exposes the singleton factories used by `Depends(...)`:

- `REPOSITORY_BACKEND=redis` ⇒ `RedisVitalsRepository` / `RedisEpisodeRepository`
  (Sorted-Set time-series + Hashes, 30-day TTL), selected only when Redis is
  reachable via `is_redis_available()`.
- Default (`memory`) ⇒ bounded in-process `InMemory*` repositories
  (single-instance dev/test).

## 4.4 SafetyShell Invariant Gate

Every forecast flows through `src/core/safety/shell.py`:

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

The shell is constructed in `src/dependencies.py` with optional
`on_fallback` and `on_stale_data` hooks that increment the `safety_shell_fallback_total`
and `stale_data_warning_total` counters — core stays framework-free; the Prometheus
hooks are wired at the adapter boundary.

## 4.5 Observability Contract

- `/health/liveness` — process is up (200).
- `/health/readiness` — repository component availability.
- `/metrics` — Prometheus text exposition; counters are **label-free**, the
  `active_episodes` gauge is keyed only by risk **state tier** (never by
  `patient_id` / `episode_id`).
- Structured JSON logs carry `correlation_id`, `patient_id`, `episode_id`, and
  the CIMD `requested_by` principal for audit.
- `X-Request-ID` is echoed on every response.

## 4.6 Episode ID Format

Episode IDs are generated as `E-<uuid>` (a `uuid4` hex truncated to 12 chars,
prefixed with `E-`, e.g. `E-a3b2c1d4e5f6`) at `create()` time in both
`InMemoryEpisodeRepository` (`src/adapters/storage/memory.py`) and
`RedisEpisodeRepository` (`src/adapters/storage/contrib/redis.py`) (see
`docs/ADR-001-episode-id-format.md`). UUIDs eliminate collisions when multiple
episodes are opened for the same patient, so the active-patient index is now a
**set** and `get_active_by_patient()` returns the most-recent active episode
deterministically (by `created_at`). Clients must capture `episode_id` from the
ingest/open response rather than constructing it.

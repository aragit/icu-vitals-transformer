# R2 Migration Log — v0.1.0 → v0.2.0

A phase-by-phase record of the transition from the monolithic v0.1.0 skill
(`_vitals_store` module-global) to the v0.2.0 **Hexagonal Skill Engine**
reference architecture.

## Phase 0 — Baseline Lock

Frozen the v0.1.0 behavior as the regression anchor:
- `src/forecasting/forecaster.py` / `src/ingestion/` / `src/models/` shims.
- `_vitals_store` raw-FHIR dict store keyed by patient.
- Legacy REST surface: `/vitals/ingest`, `/vitals/current/{id}`,
  `/vitals/forecast/{id}`, `/vitals/deterioration/{id}`, `/health/`,
  `/health/ready`, `/metrics/`.
- **180+ baseline tests pinned** (strangler compatibility gate).

## Phase 1 — Pure Core Extraction

- Promoted domain types into `src/core/domain/` (`VitalSignsWindow`, `Episode`,
  `ForecastResult`, `DeteriorationAssessment`).
- Moved ingestion/windowing into `src/core/ingestion/` + `src/core/windowing/`.
- Hardened the deterministic forecaster (`_freshness_seconds` naive-UTC-safe,
  truthiness-preserving bounds) so **strict `mypy`** passes with **zero `operator`
  ignores** and **zero baseline test changes**.

## Phase 2 — Ports, Repositories & Services

- Defined async `typing.Protocol` ports in `src/ports/repository.py` and
  `src/ports/forecaster.py`.
- Implemented `InMemoryVitalsRepository` / `InMemoryEpisodeRepository` /
  `InMemoryAssessmentRepository` (bounded deques, `asyncio.Lock`,
  SINGLE-INSTANCE-ONLY docstring).
- Added `src/adapters/forecast/deterministic.py` (async backend via
  `asyncio.to_thread`) and `src/dependencies.py` DI container wiring
  `SafetyShell(DeterministicForecastBackend())`.

## Phase 3 — Intelligence Layer (Trends & DDS)

- `src/core/forecasting/trends.py`: pure-Python least-squares slope estimator
  (zero numpy).
- `ClinicalAssessmentService.assess_episode` retrieves `get_history`, computes
  `trend_per_hour`, passes into the backend.
- `ForecastResult.contributing_factors` now reports `stale_data_warning` and
  per-channel `<field>_trend`; `assess_episode` propagates forecast signals
  into the DDS assessment envelope.

## Phase 4 — Driving Adapters & Observability

- REST v2 routes (`src/adapters/rest/routes/vitals_v2.py`, `health.py`,
  `metrics.py`) behind `Depends(get_clinical_service)`.
- `CorrelationIdMiddleware` (X-Request-ID, deprecation headers for `/vitals/*`).
- FastMCP adapter (`src/adapters/mcp/{server,tools}.py`) with tools
  `ingest_vitals`, `get_forecast`, `get_deterioration_index`, `discover_episode`.
- `src/observability/metrics.py` (label-free, alias-compatible with v0.1 names) and
  `src/observability/logging.py` (JSON, contextvars for correlation/patient/episode).

## Phase 5 — Protocol Modernization & Compliance (this phase)

- **Manifests:** `manifests/mcp.json`, `manifests/SKILL.md`.
- **Discovery:** `GET /discover` + `src/adapters/mcp/discovery.discover_capabilities()`.
- **Transport:** `MCP_TRANSPORT=http|stdio` selecting Streamable HTTP (prod) or
  stdio (dev).
- **MRTR:** `src/adapters/mcp/mrtr.py` mid-flight disambiguation for ambiguous
  episodes.
- **Auth:** `src/auth/cimd.py` CIMD/JWT principal extraction; middleware binds
  `requested_by` into logging context.
- **Storage:** `src/adapters/storage/redis.py` multi-replica backend, selected
  via `REPOSITORY_BACKEND=redis` with safe in-memory fallback.
- **Tests:** E2E workflow/parity, edge-case matrix, performance budgets,
  modernization contract tests.

## Cutover Notes

- v1 routes and `_vitals_store` remain for backward compatibility, now marked
  with `Deprecation: true` + `Link: </v2/vitals/ingest>; rel="alternate"`.
- The v2 and MCP surfaces share a single `ClinicalAssessmentService` hex-core
  singleton; migration is a transport-layer switch, not a logic rewrite.
- **Target:** 240+ tests green, `mypy src/` clean, `ruff` clean, ≥ 92 % coverage.

## Phase 6 — Production Hardening (post-migration)

- Multi-replica Redis storage selected via `REPOSITORY_BACKEND=redis` with safe
  in-memory fallback.
- MRTR disambiguation for ambiguous episode resolution.
- CIMD/JWT bearer-token principal extraction bound into the logging context.

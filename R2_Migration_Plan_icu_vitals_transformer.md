# R2 Migration Plan: ICU-Vitals-Transformer
## Hexagonal Skill Engine — Deterministic Micro-Skill Surface

**Repository:** `icu-vitals-transformer`  
**Target:** Reference architecture for cross-protocol specialized clinical skills  
**Pattern:** Strangler Fig + Branch by Abstraction + Ports & Adapters (Hexagonal)  
**Estimated Duration:** 6–7 weeks (1 phase per week)  
**Risk Level:** Low — backward-compatible until Phase 5  

---

## Executive Summary

This plan migrates `icu-vitals-transformer` from a monolithic FastAPI/MCP hybrid with module-level state to a **protocol-agnostic Hexagonal Skill Engine**. The core clinical logic becomes pure Python with zero external dependencies, while transport (MCP, REST, A2A) and storage (memory, Redis, Postgres) become swappable adapters.

| Attribute | Current State | R2 Target |
|-----------|--------------|-----------|
| **State Model** | Module-level `_vitals_store[patient_id]` | Externalized repository + Episode FSM |
| **Forecasting** | Flat-line projection (trend=0) | Least-squares trend + Safety Shell |
| **Governance** | NEWS2-inspired (misleading name) | Deterministic Deterioration Score (DDS) |
| **Transport** | `stdio` default, static tools | Streamable HTTP + capability negotiation |
| **Safety** | Ad-hoc clamping | Mandatory `SafetyShell` invariant gate |
| **Discovery** | Hardcoded 6-vital assumption | Autonomous vital discovery per episode |
| **Protocol Stack** | MCP only | MCP primary, REST secondary, A2A optional shim |

---

## 0. Migration Philosophy & Patterns

Five proven patterns govern this migration:

| Pattern | Application |
|---------|-------------|
| **Strangler Fig** | Old REST endpoints remain functional as aliases while episode-centric v2 endpoints are built alongside. No breaking changes until Phase 5. |
| **Repository Pattern** | All state lives behind protocols. FastAPI and MCP depend on the protocol, not each other. |
| **Safety Shell** | A decorator/wrapper around **any** `ForecastBackend` that enforces Type 2 invariants before output reaches any adapter. |
| **Event Sourcing (Audit)** | Forecast logs are append-only. Never updated or deleted. |
| **Branch by Abstraction** | Repository adapters (Memory → Redis → Postgres) are swappable via configuration without code changes. |

### The Core Dependency Rule (Inward Flow Only)

```
┌─────────────────────────────────────────────┐
│  ADAPTERS (MCP, REST, A2A, Storage)         │  ← Outer layers depend inward
│  depend on Ports & Core                       │
├─────────────────────────────────────────────┤
│  PORTS (Repository, ForecastBackend Protocols)│  ← Interfaces
├─────────────────────────────────────────────┤
│  CORE DOMAIN (Pure Clinical Logic)            │  ← Zero external dependencies
│  ingestion, windowing, forecasting,           │
│  governance, safety, episode FSM            │
└─────────────────────────────────────────────┘
```

**Invariant:** The Core Domain never imports from FastAPI, mcp SDK, Redis, or Prometheus.

---

## Phase 0: Foundation & Baseline Lock
**Objective:** Establish behavioral contract, CI gates, and test harness before touching domain logic.

**Duration:** 4–5 days  
**Risk:** Zero — no production code changes.

### Step 0.1 — Behavioral Audit
- [ ] Run existing `pytest -v --cov=src` and record baseline coverage percentage.
- [ ] Document current API contract in `docs/BASELINE.md`:
  - Request/response schemas for all REST endpoints
  - MCP tool signatures (`ingest_vitals`, `get_forecast`, `get_deterioration_index`)
  - Error codes and edge cases (empty observations, missing vitals)
- [ ] Identify every direct import of `mcp`, `fastapi`, `prometheus_client` inside current `src/forecasting/`, `src/governance/`, `src/ingestion/` — these will need to move to adapters in Phase 1.

### Step 0.2 — CI/CD & Quality Gates
- [ ] Create `.github/workflows/ci.yml`:
  - Python 3.12, `pytest --cov=src --cov-fail-under=80`
  - `ruff check src/ tests/`
  - `mypy src/` (strict mode)
- [ ] Create `.pre-commit-config.yaml`: `black`, `ruff`, `mypy`
- [ ] Add `pytest.ini` with markers: `unit`, `integration`, `contract`, `property`, `e2e`
- [ ] Add `pyproject.toml` sections for tool configuration.

### Step 0.3 — Backfill Critical Tests (Before Refactor)
- [ ] `tests/unit/test_fhir_parser.py`: valid LOINC, unknown LOINC, missing `valueQuantity`, malformed JSON, unit string rejection (°F vs °C).
- [ ] `tests/unit/test_windowing.py`: single record, multiple records, empty batch, out-of-order timestamps, AVPU passthrough.
- [ ] `tests/unit/test_forecaster.py`: flat-line projection, bound clamping, uncertainty growth, null vital handling.
- [ ] `tests/unit/test_deterioration.py`: boundary tests for every threshold (score 0, 2, 3, 5, 7, 20), AVPU scoring, trend modifier.
- [ ] `tests/integration/test_api_contract.py`: FastAPI `TestClient` end-to-end for ingest → current → forecast → deterioration.
- [ ] `tests/contract/test_mcp_tools.py`: Verify tool schemas match current behavior using `mcp` SDK test utilities.

### ✅ Acceptance Criteria
- CI green, coverage ≥ 80%, all existing tests pass.
- `docs/BASELINE.md` exists and documents every current behavior.

### 🛡️ Safety Checkpoint
Zero production code changes. Only tests and infrastructure.

---

## Phase 1: Hexagonal Core Extraction
**Objective:** Carve out protocol-agnostic core domain. Move all FastAPI/MCP/Prometheus imports out of domain logic.

**Duration:** 5–6 days  
**Risk:** Low — strangler shims preserve backward compatibility.

### Step 1.1 — Directory Scaffold
Create the target structure (empty `__init__.py` files, placeholder modules):

```
src/
├── core/
│   ├── domain/
│   ├── ingestion/
│   ├── windowing/
│   ├── forecasting/
│   ├── governance/
│   ├── safety/          # NEW: Explicit Safety Shell
│   └── services/
├── ports/
│   ├── repository.py
│   └── forecaster.py
├── adapters/
│   ├── mcp/
│   ├── rest/
│   ├── a2a/
│   └── storage/
└── observability/
```

### Step 1.2 — Port Definitions (`src/ports/`)
- [ ] `src/ports/repository.py`:
  - `VitalsRepository` Protocol: `append()`, `get_window()`, `get_history()`, `clear_old()`
  - `EpisodeRepository` Protocol: `create()`, `get()`, `get_active_by_patient()`, `transition()`, `update_window()`
  - `AssessmentRepository` Protocol: `append_assessment()`, `get_audit_trail()`
- [ ] `src/ports/forecaster.py`:
  - `ForecastBackend` Protocol: `forecast(current_window, horizon_minutes, trend_per_hour) -> ForecastResult`
  - `SafetyBackend` Protocol: `validate(result) -> ForecastResult` (invariant gate)

### Step 1.3 — Core Domain Models (`src/core/domain/`)
- [ ] `src/core/domain/vitals.py`: Migrate `VitalSignsWindow`, `VitalIngestionRequest` from `src/models/vitals.py`. Use pure Pydantic v2 `BaseModel` — no FastAPI-specific `Field(json_schema_extra=...)`.
- [ ] `src/core/domain/forecast.py`: Migrate `ForecastResult`, `DeteriorationAssessment`. Add `data_freshness_seconds: int` field.
- [ ] `src/core/domain/episode.py`: NEW — `EpisodeState` enum, `Episode` model with `available_vitals: set[str]`.
- [ ] `src/core/domain/disclaimer.py`: NEW — `CLINICAL_SAFETY_DISCLAIMER` constant as a code artifact.

### Step 1.4 — Pure Domain Extraction
- [ ] `src/core/ingestion/fhir_parser.py`: Copy logic from `src/ingestion/fhir_parser.py`. **Remove** `loguru` dependency — use standard `logging` or return structured parse errors. Remove `VITALS_INGESTED` counter.
- [ ] `src/core/windowing/engine.py`: Copy `window_vitals`. Fix temporal anchoring to `max(t_observations)` (not oldest record). Add AVPU handling (most-recent, not mean). Remove `loguru`.
- [ ] `src/core/forecasting/forecaster.py`: Copy `forecast_vitals`. Keep deterministic logic. Ensure **zero numpy** — use `statistics.linear_regression()` (Python 3.10+) or a 10-line pure-Python slope calculator.
- [ ] `src/core/governance/deterioration.py`: Rename scoring to **DDS (Deterministic Deterioration Score)**. Document deviation from NEWS2. Add `DDS_MAX_SCORE = 20`.
- [ ] `src/core/governance/severity.py`: Keep deterministic mapping. Add `severity_rank` helper.
- [ ] `src/core/safety/shell.py`: NEW — `SafetyShell` class implementing `SafetyBackend` Protocol:
  - Clamps all vitals to `BOUNDS`
  - Ensures `uncertainty_lower < forecasted < uncertainty_upper`
  - Ensures `deterioration_index ∈ [0, 20]`
  - Appends `stale_data_warning` to `contributing_factors` if `data_freshness_seconds > 300`
  - If any invariant violated: log CRITICAL, fallback to flat-line deterministic forecast
  - Returns validated `ForecastResult`

### Step 1.5 — Core Service Orchestrator
- [ ] `src/core/services/clinical_assessment.py`: NEW — `ClinicalAssessmentService` class:
  - Accepts injected `VitalsRepository`, `EpisodeRepository`, `ForecastBackend`
  - Method: `ingest_and_window(patient_id, observations) -> VitalSignsWindow`
  - Method: `assess_episode(episode_id) -> DeteriorationAssessment` (fetches history → computes trends → forecasts → safety shell → scores → transitions episode state)
  - **Zero imports** from `fastapi`, `mcp`, `prometheus_client`, `redis`

### Step 1.6 — Strangler Shim
- [ ] Keep old `src/` modules temporarily. Have them **delegate** to `src/core/`:
  ```python
  # src/ingestion/fhir_parser.py (old)
  from src.core.ingestion.fhir_parser import parse_batch as _parse_batch
  def parse_batch(observations): return _parse_batch(observations)
  ```
- [ ] Verify all old tests still pass without modification.

### ✅ Acceptance Criteria
- All Phase 0 tests pass.
- `mypy src/core` passes with zero errors.
- No `fastapi`, `mcp`, `prometheus_client` imports in `src/core/` or `src/ports/`.

### 🛡️ Safety Checkpoint
Domain logic is pure. Old adapters still work via delegation shims.

---

## Phase 2: Repository & State Safety
**Objective:** Eliminate `_vitals_store` circular dependency. Implement bounded, thread-safe repositories.

**Duration:** 5–6 days  
**Risk:** Low — in-memory default preserves current semantics.

### Step 2.1 — In-Memory Bounded Repository
- [ ] `src/adapters/storage/memory.py`:
  - `InMemoryVitalsRepository`: `collections.deque(maxlen=1000)` per episode. Thread-safe via `asyncio.Lock`.
  - `InMemoryEpisodeRepository`: `dict[str, Episode]` storage. Lock-protected transitions.
  - `InMemoryAssessmentRepository`: `deque(maxlen=10000)` append-only audit log.
  - **Add docstring:** `⚠️ SINGLE-INSTANCE ONLY. For dev/test. Production: use RedisRepository.`

### Step 2.2 — Repository Integration
- [ ] `src/dependencies.py`: NEW — `get_vitals_repo()`, `get_episode_repo()`, `get_assessment_repo()` using `app.state` or singleton pattern.
- [ ] Update old `src/api/routes/vitals.py`: Replace `_vitals_store` with repository calls via `Depends(get_vitals_repo)`.
- [ ] Update old `src/mcp_server/server.py`: Replace `_vitals_store` with injected repository. Remove circular import.

### Step 2.3 — Episode State Machine Integration
- [ ] `src/core/services/clinical_assessment.py`:
  - On `ingest_and_window`: if no active episode for patient, auto-create via `EpisodeRepository.create()`.
  - On `assess_episode`: after DDS scoring, call `EpisodeRepository.transition()` with trigger.
- [ ] `src/core/governance/deterioration.py`: Add episode-state modifier (e.g., `TRENDING_NEGATIVE` sustained adds +1).

### Step 2.4 — Autonomous Discovery
- [ ] `src/core/discovery/vital_discovery.py`: NEW — `discover_available_vitals(episode_id, repo) -> set[str]`.
- [ ] Update `Episode.available_vitals` on every ingest.

### Step 2.5 — Test Coverage
- [ ] `tests/integration/test_repositories.py`: Test all three in-memory repositories. Verify deque eviction at maxlen. Verify thread safety.
- [ ] `tests/unit/test_episode_fsm.py`: Test all valid state transitions. Test invalid transitions are rejected.
- [ ] `tests/unit/test_safety_shell.py`: Test bound clamping, stale data warning, fallback behavior.

### ✅ Acceptance Criteria
- All old tests pass.
- New repository tests pass.
- `_vitals_store` module-level dict is deleted.
- Episode FSM transitions deterministically.

### 🛡️ Safety Checkpoint
No module-level mutable state. All data access via repository protocols. Episode isolation enforced.

---

## Phase 3: Intelligence Layer (Trends & DDS)
**Objective:** Make the forecaster actually extrapolate trends instead of flat-lining. Formalize DDS.

**Duration:** 4–5 days  
**Risk:** Low — Safety Shell catches any trend computation errors.

### Step 3.1 — Trend Computation Engine
- [ ] `src/core/forecasting/trends.py`: NEW — `compute_trends(windows: list[VitalSignsWindow]) -> dict[str, float]`:
  - Least-squares slope per vital type.
  - Require `min_windows=2`. Return `{}` otherwise (safe fallback).
  - Skip `None` values gracefully.
  - Pure Python — no numpy.

### Step 3.2 — DeterministicBackend v2
- [ ] `src/core/forecasting/backends.py`: NEW — `DeterministicBackend` implementing `ForecastBackend` Protocol:
  - Consumes `trend_per_hour` dict.
  - If empty, falls back to flat-line (preserving old behavior).
  - Returns `ForecastResult` with populated `uncertainty_lower/upper`.

### Step 3.3 — Safety Shell Integration
- [ ] Update `ClinicalAssessmentService.assess_episode()`:
  ```python
  raw_backend = DeterministicBackend()
  safe_backend = SafetyShell(raw_backend)  # Invariant gate
  forecast = safe_backend.forecast(...)
  ```

### Step 3.4 — DDS Formalization
- [ ] Update all docstrings: "NEWS2-inspired" → "DDS (Deterministic Deterioration Score)".
- [ ] Update `SKILL.md` (if drafted) and `mcp.json` descriptions.
- [ ] Add `DDS_VERSION = "1.0.0"` constant for audit trail versioning.

### Step 3.5 — Data Freshness
- [ ] `src/core/windowing/engine.py`: Compute `data_freshness_seconds = now - max(t_observations)`.
- [ ] `src/core/domain/forecast.py`: Include `data_freshness_seconds` in `ForecastResult`.
- [ ] `SafetyShell`: If freshness > 300s, append `"stale_data_warning"` to `contributing_factors`.

### ✅ Acceptance Criteria
- Forecasts with ≥2 historical windows show non-zero trends.
- Safety Shell tests verify clamping and fallback.
- DDS naming is consistent across codebase.

### 🛡️ Safety Checkpoint
Every forecast passes through Safety Shell. No backend can bypass invariants.

---

## Phase 4: Adapter Implementation
**Objective:** Build clean MCP, REST, and observability adapters around the pure core.

**Duration:** 5–6 days  
**Risk:** Medium — new endpoints must not break old clients.

### Step 4.1 — REST Adapter (`src/adapters/rest/`)
- [ ] `src/adapters/rest/routes/vitals.py`: NEW v2 endpoints using `ClinicalAssessmentService`:
  - `POST /v2/vitals/ingest` (episode-aware)
  - `GET /v2/episodes/{episode_id}/current`
  - `GET /v2/episodes/{episode_id}/forecast`
  - `GET /v2/episodes/{episode_id}/deterioration`
  - `POST /v2/patients/{patient_id}/episodes` (explicit episode creation)
  - `GET /v2/episodes/{episode_id}/discovery`
- [ ] `src/adapters/rest/middleware.py`: Correlation ID injection (`X-Request-ID`).
- [ ] Keep old `/vitals/*` routes in `src/api/routes/vitals.py` (Strangler Fig) but add `Deprecation: true` headers.

### Step 4.2 — MCP Adapter (`src/adapters/mcp/`)
- [ ] `src/adapters/mcp/server.py`: MCP server lifecycle using `mcp` SDK.
- [ ] `src/adapters/mcp/tools.py`: Tool bindings calling `ClinicalAssessmentService`:
  - `ingest_vitals` (patient_id → auto-resolve/create episode)
  - `get_forecast` (episode_id, horizon_minutes)
  - `get_deterioration_index` (episode_id)
  - `discover_episode` (patient_id → episode metadata + available vitals)
- [ ] Inject `CLINICAL_SAFETY_DISCLAIMER` into every tool description.

### Step 4.3 — Observability Adapter (`src/observability/`)
- [ ] `src/observability/metrics.py`: Label-free Prometheus counters/histograms:
  - `vitals_ingested_total`, `forecasts_generated_total`, `assessments_total`
  - `forecast_latency_seconds`, `trend_computation_latency_seconds`
  - `safety_shell_fallback_total` (NEW — tracks invariant violations)
  - `episode_state` Gauge (values: 0=NORMAL, 1=WARNING, 2=ALERT, 3=EMERGENCY, 4=CRITICAL)
- [ ] `src/observability/logging.py`: Structured JSON logging with correlation IDs, patient_id, episode_id, tool_name.

### Step 4.4 — REST Metrics & Health
- [ ] `src/adapters/rest/routes/health.py`: Liveness, readiness, deep health (repository connectivity).
- [ ] `src/adapters/rest/routes/metrics.py`: Prometheus exposition endpoint.

### ✅ Acceptance Criteria
- v2 REST endpoints pass integration tests.
- MCP tools pass contract tests.
- Prometheus metrics are scrapeable.
- Old v1 endpoints still work.

### 🛡️ Safety Checkpoint
Observability layer has zero patient_id/episode_id labels in metrics. Audit logs are structured JSON.

---

## Phase 5: Protocol Modernization & Compliance
**Objective:** Achieve MCP 2026-07-28 compliance, capability negotiation, and manifest publication.

**Duration:** 4–5 days  
**Risk:** Low — additive features, no breaking changes.

### Step 5.1 — MCP 2026 Transport
- [ ] `src/adapters/mcp/server.py`: Implement Streamable HTTP as primary transport.
- [ ] Keep `stdio` as dev fallback via config `MCP_TRANSPORT`.
- [ ] Stateless per-request handling. No session affinity.

### Step 5.2 — Capability Negotiation
- [ ] `src/adapters/mcp/discovery.py`: `discover_capabilities()` returning:
  - Tools list with `_meta.determinism`, `_meta.side_effects`
  - Resources list (`clinical://bounds/v1`, `clinical://loinc-mapping/v1`)
  - Safety boundary declaration
- [ ] REST: `GET /discover` returning JSON manifest.

### Step 5.3 — Manifests
- [ ] `manifests/mcp.json`: Server capability manifest (tools, resources, extensions).
- [ ] `manifests/SKILL.md`: Agent procedural knowledge:
  - When to call `ingest_vitals` vs `discover_episode`
  - How to interpret DDS severity tiers
  - Safety boundary: "This tool never initiates clinical action"
- [ ] `manifests/AGENT_CARD.json`: A2A Agent Card stub (capabilities, endpoint, skills).

### Step 5.4 — MRTR Support
- [ ] `src/adapters/mcp/mrtr.py`: Helper for mid-flight elicitation.
- [ ] If `episode_id` missing and patient has multiple active episodes, return MRTR instead of guessing.

### Step 5.5 — Auth Stubs
- [ ] `src/adapters/rest/middleware.py`: `require_auth()` dependency (optional in dev, enforced in prod).
- [ ] `src/auth/cimd.py`: CIMD validation stubs. Parse `iss`, verify issuer-bound tokens.
- [ ] Inject `requested_by` principal into audit logs.

### ✅ Acceptance Criteria
- MCP client can connect via Streamable HTTP, call `discover_capabilities`, then `ingest_vitals`, then `get_deterioration_index`.
- `SKILL.md` and `mcp.json` are present and valid.

### 🛡️ Safety Checkpoint
Auth middleware rejects unauthorized requests before domain logic. Safety Shell is not bypassable.

---

## Phase 6: Production Hardening
**Objective:** Add persistent storage, multi-replica support, and operational readiness.

**Duration:** 4–5 days  
**Risk:** Medium — new infrastructure dependencies.

### Step 6.1 — Redis Adapter
- [ ] `src/adapters/storage/redis.py`:
  - `RedisVitalsRepository`: Time-series sorted sets per episode (`zadd` with timestamp score). TTL 30 days.
  - `RedisEpisodeRepository`: Hash per episode + state index.
- [ ] `docker-compose.yml`: Add Redis service.
- [ ] Config: `REDIS_URL`, `REPOSITORY_BACKEND=redis`.

### Step 6.2 — Postgres Adapter (Optional but Recommended)
- [ ] `src/adapters/storage/postgres.py`:
  - `PostgresEpisodeRepository`: SQLAlchemy async model for episodes.
  - `PostgresAssessmentRepository`: Append-only `forecast_logs` table.
- [ ] Alembic migrations in `migrations/`.
- [ ] Config: `DATABASE_URL`, `REPOSITORY_BACKEND=postgres`.

### Step 6.3 — Repository Selection
- [ ] `src/dependencies.py`: Select adapter via `REPOSITORY_BACKEND` env var (`memory`, `redis`, `postgres`).

### Step 6.4 — Load & Chaos Testing
- [ ] `tests/load/locustfile.py`: 100 concurrent episodes, sustained ingest/forecast cycles.
- [ ] Chaos test: Kill Redis mid-operation. Verify graceful 503 or memory fallback (if configured).

### Step 6.5 — Final Cleanup
- [ ] Move old `src/api/`, `src/mcp_server/`, `src/models/` to `src/_legacy/` (or delete if fully strangler-figged).
- [ ] Update `README.md` with architecture diagram and R2 changelog.
- [ ] Tag release: `v0.2.0`.

### ✅ Acceptance Criteria
- Load tests pass at 100 concurrent episodes.
- Redis adapter passes full test suite.
- Docker Compose brings up full stack with one command.
- Old v1 endpoints removed or clearly deprecated.

### 🛡️ Safety Checkpoint
Production adapters preserve append-only audit log. Multi-replica deployments share state via Redis/Postgres.

---

## Phase 7: A2A Extension (Optional / Future)
**Objective:** Wrap the core as an A2A-capable agent facade without touching domain logic.

**Duration:** 2–3 days (when needed)  
**Risk:** Zero — pure translation layer.

### Step 7.1 — A2A Task Handler
- [ ] `src/adapters/a2a/task_handler.py`:
  - Receive A2A Task → extract parameters → call `ClinicalAssessmentService` → package result as A2A Artifact.
  - No planning, no memory, no delegation — pure translation layer.

### Step 7.2 — A2A Discovery
- [ ] `src/adapters/a2a/discovery.py`: Serve `/.well-known/agent.json` from `manifests/AGENT_CARD.json`.

### Step 7.3 — Integration
- [ ] Add A2A transport to `src/main.py` if `A2A_ENABLED=true`.

### ✅ Acceptance Criteria
- A2A client can discover the skill via Agent Card and submit a Task.
- Response is a valid A2A Artifact containing the DDS assessment.

---

## Cross-Cutting Concerns

### Test Strategy

| Layer | Test File Pattern | Markers |
|-------|-------------------|---------|
| Core Domain | `tests/unit/core/test_*.py` | `unit` |
| Ports (Protocols) | `tests/unit/ports/test_*.py` | `unit` |
| Repositories | `tests/integration/storage/test_*.py` | `integration` |
| REST Adapters | `tests/integration/rest/test_*.py` | `integration` |
| MCP Adapters | `tests/contract/mcp/test_*.py` | `contract` |
| Safety Invariants | `tests/unit/core/safety/test_shell.py` | `unit`, `property` |
| Load | `tests/load/test_*.py` | `load`, `e2e` |

### Observability Checklist
- [ ] Every forecast has a trace ID.
- [ ] Every state transition is logged with `episode_id`, `old_state`, `new_state`, `trigger`, `score`.
- [ ] Prometheus metrics have no `patient_id` or `episode_id` labels.
- [ ] Audit logs are structured JSON, append-only, with retention policy.

### Documentation Deliverables
- [ ] `docs/ARCHITECTURE.md` — C4 diagrams (Context, Container, Component, Code).
- [ ] `docs/MIGRATION.md` — Phase-by-phase changelog.
- [ ] `docs/SAFETY.md` — Type 2 invariant specification and proof sketches.
- [ ] `manifests/SKILL.md` — Agent-facing procedural knowledge.
- [ ] `manifests/mcp.json` — MCP capability manifest.
- [ ] `manifests/AGENT_CARD.json` — A2A capability stub.

---

## Dependency Graph & Critical Path

```
Phase 0 (Tests + CI)
    │
    ▼
Phase 1 (Hexagonal Core Extraction)
    │
    ├──► Phase 2 (Repositories) ──► Phase 3 (Trends + Safety Shell)
    │                                  │
    │                                  ▼
    │                           Phase 4 (Adapters: REST + MCP)
    │                                  │
    │                                  ▼
    │                           Phase 5 (MCP 2026 Compliance)
    │                                  │
    │                                  ▼
    │                           Phase 6 (Production Hardening)
    │                                  │
    └──────────────────────────────────┘
                                       ▼
                                  Phase 7 (A2A Extension)
```

**Critical Path:** Phase 1 → Phase 2 → Phase 3 → Phase 4.  
Phases 5 and 6 can overlap with Phase 4 once core is stable.

---

## Rollback Points

| Phase | Rollback Trigger | Action |
|-------|-----------------|--------|
| 1 | Core extraction breaks old tests | Revert to shim delegation; fix core unit tests |
| 2 | Repository performance unacceptable | Keep in-memory but add explicit multi-replica warnings |
| 3 | Trend computation produces NaN/Inf | Safety Shell catches; fallback to flat-line |
| 4 | MCP SDK compatibility issues | Keep stdio transport; delay Streamable HTTP |
| 6 | Redis adapter unstable | Fallback to in-memory with single-replica constraint |

---

## Definition of Done (R2 Complete)

1. [ ] **Core Domain** has zero imports from FastAPI, MCP SDK, Redis, or Prometheus.
2. [ ] **Safety Shell** is mandatory — no backend output reaches an adapter without passing invariant checks.
3. [ ] **Trend Computation** is active for all vitals with ≥2 historical windows.
4. [ ] **Episode FSM** tracks clinical monitoring lifecycle with deterministic transitions.
5. [ ] **MCP 2026-07-28** transport is primary; capability negotiation is implemented.
6. [ ] **Audit Trail** is append-only and queryable by `episode_id`.
7. [ ] **Production Adapters** (Redis + optional Postgres) pass full test suite.
8. [ ] **Load Tests** confirm stability at 100 concurrent episodes.
9. [ ] **CI Green** with ≥80% coverage.
10. [ ] **SKILL.md** and **mcp.json** are present and describe the safety boundary.

---

## Appendix A: Target Directory Layout (Final State)

```
icu-vitals-transformer/
├── config/
│   ├── default.yaml
│   └── logging.yaml
│
├── manifests/
│   ├── mcp.json
│   ├── SKILL.md
│   └── AGENT_CARD.json
│
├── src/
│   ├── core/
│   │   ├── domain/
│   │   │   ├── vitals.py
│   │   │   ├── forecast.py
│   │   │   ├── episode.py
│   │   │   └── disclaimer.py
│   │   ├── ingestion/
│   │   │   └── fhir_parser.py
│   │   ├── windowing/
│   │   │   └── engine.py
│   │   ├── forecasting/
│   │   │   ├── trends.py
│   │   │   ├── backends.py
│   │   │   └── forecaster.py
│   │   ├── governance/
│   │   │   ├── deterioration.py
│   │   │   └── severity.py
│   │   ├── safety/
│   │   │   └── shell.py
│   │   ├── discovery/
│   │   │   └── vital_discovery.py
│   │   └── services/
│   │       └── clinical_assessment.py
│   │
│   ├── ports/
│   │   ├── repository.py
│   │   └── forecaster.py
│   │
│   ├── adapters/
│   │   ├── mcp/
│   │   │   ├── server.py
│   │   │   ├── tools.py
│   │   │   ├── discovery.py
│   │   │   └── mrtr.py
│   │   ├── rest/
│   │   │   ├── routes/
│   │   │   │   ├── vitals.py
│   │   │   │   ├── health.py
│   │   │   │   └── metrics.py
│   │   │   └── middleware.py
│   │   ├── a2a/
│   │   │   ├── task_handler.py
│   │   │   └── discovery.py
│   │   └── storage/
│   │       ├── memory.py
│   │       ├── redis.py
│   │       └── postgres.py
│   │
│   ├── observability/
│   │   ├── metrics.py
│   │   └── logging.py
│   │
│   ├── auth/
│   │   └── cimd.py
│   │
│   └── dependencies.py
│
├── tests/
│   ├── unit/
│   │   ├── core/
│   │   └── ports/
│   ├── integration/
│   │   ├── storage/
│   │   └── rest/
│   ├── contract/
│   │   └── mcp/
│   ├── load/
│   └── conftest.py
│
├── docs/
│   ├── BASELINE.md
│   ├── ARCHITECTURE.md
│   ├── MIGRATION.md
│   └── SAFETY.md
│
├── docker/
│   └── docker-compose.yml
│
├── migrations/
│   └── (alembic)
│
├── pyproject.toml
├── pytest.ini
├── .pre-commit-config.yaml
├── .github/
│   └── workflows/
│       └── ci.yml
└── README.md
```

---

## Appendix B: Protocol Positioning Summary

| Protocol | Role in Architecture | When This Skill Uses It |
|----------|----------------------|------------------------|
| **MCP** | Vertical: Agent ↔ Tool | Primary. The skill exposes `ingest_vitals`, `get_forecast`, `get_deterioration_index` as MCP tools. |
| **REST** | Horizontal: Service ↔ Service | Secondary. Legacy EHR integrations, health probes, Prometheus metrics. |
| **A2A** | Horizontal: Agent ↔ Agent | Optional extension. Only if another agent delegates a task directly to this skill. The skill itself does not delegate. |

**Rule:** This repo is a **tool**, not an agent. It speaks MCP natively. A2A is a thin facade added only if the surrounding multi-agent architecture requires it.

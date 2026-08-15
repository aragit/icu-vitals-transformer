# BASELINE.md — ICU Vitals Transformer (v0.9.1)

> **Deprecation notice (v0.9.1):** The v1 REST surface
> (`src/api/routes/vitals.py` — `POST /vitals/ingest`, `GET /vitals/{current,
> forecast,deterioration}/{patient_id}`, `GET /health/`, `GET /metrics/`) and the
> legacy MCP stdio entry point (`src/mcp_server/`) have been **retired and
> removed**. Use the **v2 REST API** (`/v2/*`) and the **FastMCP** driving
> adapter (`src/adapters/mcp`). The v2 request lifecycle is episode-keyed:
> `POST /v2/patients/{patient_id}/episodes` → `POST /v2/vitals/ingest` →
> `GET /v2/episodes/{episode_id}/{current,forecast,deterioration,discovery}`.
> Every v2 response embeds the `_meta` envelope (clinical disclaimer +
> `data_freshness_seconds`). Legacy module paths
> (`src/ingestion`, `src/forecasting`, `src/governance`, `src/models`,
> `src/api`, `src/mcp_server`) now live under `src/core/*` / `src/adapters/*`.

This document locks down the **behavioral contract** of the
`icu-vitals-transformer` repository at v0.9.1. It is the source of truth that
the test suite asserts against. Any deviation, unless explicitly called out as a
refactoring objective, is a regression.

> **Scope rule:** `src/core` and `src/ports` contain the framework-free clinical
> engines and port protocols; `src/adapters`, `src/main`, `src/config`,
> `src/dependencies`, `src/auth` and `src/observability` are framework wiring.
> Core and ports are type-checked strictly with no exemptions; the remaining
> non-core modules (`src/config`, `src/observability`, `src/main`) carry scoped
> mypy/ruff baseline overrides in `pyproject.toml`.

---

## 1. Architecture Overview

```
HTTP clients / local agents
   │
   ├──► FastAPI app            (src/main.py)
   │        └─ GET /            (root landing)
   │        └─ GET /health/liveness
   │        └─ GET /health/readiness
   │        └─ GET /metrics
   │        └─ POST  /v2/patients/{patient_id}/episodes
   │        └─ POST  /v2/vitals/ingest
   │        └─ GET   /v2/episodes/{episode_id}/current
   │        └─ GET   /v2/episodes/{episode_id}/forecast
   │        └─ GET   /v2/episodes/{episode_id}/deterioration
   │        └─ GET   /v2/episodes/{episode_id}/discovery
   │        └─ GET   /discover     (src/adapters/rest/routes/discovery.py)
   │
   └──► FastMCP server          (src/adapters/mcp/server.py — create_mcp_server)
            tools: ingest_vitals, get_forecast,
                   get_deterioration_index, discover_episode,
                   discover_capabilities

Hex core (framework-free): src/core/** + src/ports/**
Driving adapters:          src/adapters/** (REST + MCP)
Shared state:              src/vitals_state.py → _vitals_store: dict[str, list[dict]]
                           (reset in test fixtures; production uses src.dependencies.get_vitals_repo())
```

### Request lifecycle (v2)
1. A FHIR R4 `Observation` (or batch) enters either `POST /v2/vitals/ingest`
   (HTTP) or the `ingest_vitals` MCP tool.
2. `src/core/ingestion/fhir_parser.parse_batch` → `parse_observation`
   reduces each Observation to a flat record:
   `{patient_id, vital_type, value, timestamp, unit}` (with unit validation and
   AVPU resolution — see §9).
3. Records are appended to the shared `_vitals_store[patient_id]`, then
   `src/core/windowing/engine.window_vitals(parsed, patient_id, anchor="recent")`
   aggregates them into a `VitalSignsWindow` (the v2 service anchors on the most
   recent record), auto-opens/resolves the active episode, and persists the
   window.
4. `src/core/forecasting/forecaster.forecast_vitals(window, horizon, trend_per_hour)`
   produces a single `ForecastResult` (linear trend extrapolation + clinical
   clamping via the SafetyShell).
5. `src/core/services/clinical_assessment.assess_episode` runs the forecast, then
   `src/core/governance/deterioration.compute_dds(...)` + `severity_from_score`
   to produce the `DeteriorationAssessment` (dds score, severity tier,
   contributing factors).

### Component map
| Concern | Module | Notes |
|---|---|---|
| Config | `src/config.py` | `pydantic-settings` `Settings`; horizons 60/240/720. |
| Ingestion | `src/core/ingestion/fhir_parser.py` | LOINC → vital_type map (6 codes) + unit validation. |
| Windowing | `src/core/windowing/engine.py` | 5-minute sliding window, anchor on most recent record. |
| Forecast | `src/core/forecasting/forecaster.py` | Linear trend extrapolation + clinical clamping. |
| Trends | `src/core/forecasting/trends.py` | Per-channel least-squares slope (hourly). |
| Safety | `src/core/safety/` | SafetyShell: pure copy + clamp to `CLINICAL_BOUNDS`. |
| Governance | `src/core/governance/{deterioration,severity}.py` | NEWS2-inspired DDS scoring. |
| Models | `src/core/domain/{vitals,forecast,episode}.py` | Pydantic BaseModel contracts. |
| Services | `src/core/services/clinical_assessment.py` | Orchestration (ingest→window→forecast→DDS). |
| Observability | `src/observability/metrics.py` | Prometheus counters/histograms. |
| REST adapter | `src/adapters/rest/` | v2 `/v2/*` routes + `_meta` envelope. |
| MCP adapter | `src/adapters/mcp/` | FastMCP tools + `_meta` envelope. |

---

## 2. REST API (FastAPI) — v2 Active Routes

The application is created in `src/main.py`. v2 routers are mounted under `/v2`
(via `src/adapters/rest/routes/vitals_v2.py`) alongside the v2 `/health`,
`/metrics`, and `/discover` routes.

### `GET /`
Root/landing endpoint.
- Response `200`:
  ```json
  { "name": "icu-vitals-transformer", "version": "0.9.1", "status": "operational" }
  ```

### `GET /health/liveness`
Liveness probe.
- Response `200`:
  ```json
  { "status": "ok" }
  ```

### `GET /health/readiness`
Readiness probe (reports repository component status).
- Response `200`:
  ```json
  { "status": "ready", "components": { "vitals_repository":..., "episode_repository":..., "assessment_repository":... } }
  ```

### `GET /metrics`
Prometheus exposition endpoint, media-type `text/plain`.

### `POST /v2/vitals/ingest`
Ingest a batch of FHIR R4 Observations; auto-resolve (or open) the active episode.
- Request body (`VitalsIngestRequest`):
  ```json
  { "patient_id": "PT-001", "observations": [ { ...FHIR Observation... } ] }
  ```
- Behavior: `parse_batch` → 400 "No valid observations parsed" if empty;
  `window_vitals(..., anchor="recent")` → 400 if no valid window;
  auto-opens a `NORMAL` episode for the patient when none is active.
- Response `200` → windowed `VitalSignsWindow` JSON, plus `episode_id` and `_meta`.

### `POST /v2/patients/{patient_id}/episodes`
Explicitly open a new monitoring episode for a patient.
- Response `200` → `{ episode_id, patient_id, ...episode fields, _meta }`.

### `GET /v2/episodes/{episode_id}/current`
Latest `VitalSignsWindow` for an episode.
- 404 if the episode is unknown or no vitals are stored.
- Response `200` → `VitalSignsWindow` JSON + `episode_id` + `_meta`.

### `GET /v2/episodes/{episode_id}/forecast?horizon_minutes=60`
Single-horizon trend forecast for an episode (`horizon_minutes` ∈ [60,720],
default 60).
- 404 if the episode/vitals are unknown.
- Response `200` → `ForecastResult` JSON + `_meta`.

### `GET /v2/episodes/{episode_id}/deterioration`
DDS index, severity tier and contributing factors for an episode's latest
window.
- 404 if the episode/vitals are unknown.
- Response `200` → `DeteriorationAssessment` JSON (`ensemble_score`, `severity`,
  `contributing_factors`) + `episode_id` + `_meta`.

### `GET /v2/episodes/{episode_id}/discovery`
List the active vital channels present in an episode's latest window.
- Response `200` → `{ episode_id, channels: [...], _meta }`.

### `GET /discover`
Capability matrix (registered tools, resources, safety bounds).

### `_meta` envelope
Every `/v2/*` payload embeds:
```json
"_meta": { "clinical_disclaimer": "<CLINICAL_SAFETY_DISCLAIMER>", "data_freshness_seconds": <int> }
```

---

## 3. MCP Tools — v2 (FastMCP)

Defined in `src/adapters/mcp/tools.py`, registered onto a `FastMCP` instance by
`src/adapters/mcp/server.create_mcp_server()`. Invocation is via
`server.call_tool(name, arguments)`. All tools return JSON dicts embedding the
`_meta` envelope (clinical disclaimer + data freshness).

### `ingest_vitals`
- Input: `{ patient_id: str, observations: list[dict] }` (both required).
- Behavior: parse batch → window (anchor=recent) → persist → open/initialize the
  active episode; returns the `VitalSignsWindow` (+ `episode_id`, `_meta`).
- Raises (runtime-wrapped) on empty/invalid observations
  (`{ "error": "No valid observations parsed" }`, etc.).

### `get_forecast`
- Input: `{ episode_id: str, horizon_minutes?: int (60..720, default 60) }`.
- Behavior: window → trend → SafetyShell-sanitized forecast; returns
  `ForecastResult` (+ `_meta`). Error for unknown episode.

### `get_deterioration_index`
- Input: `{ episode_id: str }`.
- Behavior: run `get_forecast`, then `compute_dds`; returns
  `DeteriorationAssessment` (`ensemble_score`, `severity`,
  `contributing_factors`) + `episode_id` + `_meta`.

### `discover_episode`
- Input: `{ patient_id: str }`.
- Behavior: returns the active episode, or an MRTR disambiguation payload when
  multiple active episodes exist.

### `discover_capabilities`
- Input: `{}`.
- Behavior: returns the server capability matrix (tools, resources, safety bounds).

### Transport entry point
`src/adapters/mcp/server.run_mcp_server` selects `MCP_TRANSPORT` (`http` →
streamable-http, `stdio` for local dev).

---

## 4. Data Contracts (Models)

`src/core/domain/{vitals,forecast,episode}.py`. Bounds are expressed as the
`CLINICAL_BOUNDS` constants and applied by `clamp()` at construction and
serialization — there are **no** `Field(ge=, le=)` validators (see §9.3). An
out-of-range value constructs successfully and is clamped downstream by the
SafetyShell.

### `VitalSignsWindow` (`src/core/domain/vitals.py`)
```
patient_id: str
window_start, window_end: datetime
heart_rate, systolic_bp, diastolic_bp, spo2, respiratory_rate, temperature:
    Optional[float]
avpu: Optional[str]   (pattern ^[AVPU]$)
```
Physiological caps: heart_rate/systolic_bp ∈ [0,300]; diastolic_bp ∈ [0,200];
spo2 ∈ [0,100]; respiratory_rate ∈ [0,60]; temperature ∈ [30,45].

### `ForecastResult` (`src/core/domain/forecast.py`)
```
patient_id: str
horizon_minutes: int   [60..720]
forecasted_vitals, uncertainty_lower, uncertainty_upper: VitalSignsWindow
deterioration_index: float  [0..20]
severity: str   ^(NORMAL|WARNING|ALERT|EMERGENCY)$
data_freshness_seconds: int
```

### `DeteriorationAssessment` (`src/core/domain/forecast.py`)
```
patient_id: str
ensemble_score: float  [0..20]
severity: str   ^(NORMAL|WARNING|ALERT|EMERGENCY)$
contributing_factors: list[str]
```
(`ensemble_score` is the DDS score clipped to [0,20]; there is no weighted
multi-horizon ensemble in v2.)

### `_meta` envelope (all v2 REST/MCP responses)
```
{ "clinical_disclaimer": "<CLINICAL_SAFETY_DISCLAIMER>", "data_freshness_seconds": <int> }
```

---

## 5. Core Algorithms (Baseline Behavior)

### 5.1 FHIR parsing — `parse_observation` (`src/core/ingestion/fhir_parser.py`)
- Accepts only `resourceType == "Observation"` (else `ValueError`).
- `patient_id`: from `subject.reference` with `Patient/` stripped; defaults
  to `"unknown"` when absent.
- LOINC code: first `code.coding[].code` whose `system` ends with
  `loinc.org`; looked up in `LOINC_CODES`.
- `LOINC_CODES` mapping:
  | LOINC | vital_type |
  |---|---|
  | 8867-4 | heart_rate |
  | 8480-6 | systolic_bp |
  | 8462-4 | diastolic_bp |
  | 2708-6 | spo2 |
  | 9279-1 | respiratory_rate |
  | 8310-5 | temperature |
- Unknown/missing LOINC → logs warning, returns `{}` (skipped by `parse_batch`).
- `value`: from `valueQuantity.value` first; falls back to `valueString`.
  If neither present, `value` is `None` (record still emitted).
- `timestamp`: `effectiveDateTime` → `issued` → `datetime.utcnow().isoformat()`.
- `unit`: `valueQuantity.unit` (None if valueQuantity absent).

### 5.2 Windowing — `window_vitals` (`src/core/windowing/engine.py`)
- Empty input → `None`.
- Filters records by `patient_id`; if none for patient → `None`.
- `anchor` is a required argument (`"oldest"` | `"recent"`); the v2 service uses
  `"recent"` (window spans the most-recent record + 5 min). The engine also
  supports `"oldest"` (legacy v1 default behaviour — see §6).
- Sorts records by `timestamp` as a lexicographic string (ISO-8601 UTC safe).
- `window_start = anchor record timestamp`; `window_end = window_start + 5 min`
  (default `window_minutes=5`).
- Only records within the window are included.
- Aggregates each vital type by **mean** (rounded to 2 dp).
- Non-numeric values are logged and skipped (excluded from mean).
- `avpu` is aggregated separately (last non-empty wins) and is reachable
  via ingestion (SNOMED CT resolution — see §9.1).

### 5.3 Forecasting — `forecast_vitals` (`src/core/forecasting/forecaster.py`)
- Flat linear extrapolation:
  `extrapolated = current + trend_per_hour * (horizon_minutes / 60)`.
- Trend slopes are computed from the patient's prior windows via
  `src/core/forecasting/trends.compute_channel_slope` (per-channel least
  squares, hourly); with a single window every trend defaults to `0.0`
  (flat-line).
- Each extrapolated value is **clamped** to clinical bounds (via `clamp()`
  and the SafetyShell): heart_rate/systolic_bp ∈ [0,300], diastolic_bp ∈
  [0,200], spo2 ∈ [0,100], respiratory_rate ∈ [0,60], temperature ∈ [30,45].
- `None` channels stay `None` (no imputation).
- Uncertainty bounds: `uncertainty(h) = 2.0 * (1 + 0.1 * h/60)`;
  lower = `clamp(extrapolate - uncertainty)`, upper = `extrapolate + uncertainty`
  (lower/upper clamped, upper re-anchored ≥ extrapolated). Bounds grow with
  horizon (1h≈2.2, 4h≈2.8, 12h≈4.4).
- `deterioration_index` defaults to `0.0` and `severity` to `"NORMAL"` in the
  raw forecast; v2 scores the forecast via `assess_episode` (§5.4).

### 5.4 Assessment — DDS (v2)
- `ClinicalAssessmentService.assess_episode` runs a single-horizon forecast
  (`forecast_episode`, default 60 min) then classifies via DDS:
  `compute_dds(forecast.forecasted_vitals)` → `(score, factors)`,
  `severity_from_score(score)`, `ensemble_score = round(min(score, 20.0), 2)`.
- (The legacy multi-horizon weighted ensemble — `ensemble_forecast` /
  `ensemble_deterioration_index` / `HORIZON_WEIGHTS` — was retired in v0.9.1;
  v2 scores a single trend-anchored forecast. See §9.)
- `contributing_factors` = DDS pathology factors + any forecast-level factors
  (e.g. `heart_rate_trend`); max possible DDS score = 20.

### 5.5 Governance — scoring (`src/core/governance/{deterioration,severity}.py`)
- `compute_dds(vitals, trend="stable")` → `(score, factors)`.
- NEWS2-inspired per-vital scoring:
  - RR: `<8 or >25` → 3; `>20` → 2.
  - SpO2: `<91` → 3; `<93` → 2; `<95` → 1.
  - SBP: `<90 or >220` → 3; `<100` → 2.
  - HR: `<40 or >130` → 3; `>110` → 2.
  - Temp: `<35.0` → 3; `>39.0` → 2.
  - AVPU `!= "A"` → 3.
  - `trend == "rapidly_deteriorating"` → +2.
  - Max possible score = 20.
- `severity_from_score(score, trend="stable")`:
  `>=7 or "critical"` → EMERGENCY; `>=5` → ALERT; `>=3` → WARNING; else NORMAL.
- Risk tiers exposed at the model layer are `NORMAL/WARNING/ALERT/EMERGENCY`.

---

## 6. Legacy Limitations

These are constraints carried over from the Phase 0 baseline; each notes its
v0.9.1 status. The Phase 0 backfilled tests asserted the baseline behaviour
(including these); v0.9.1 retires several (see §9).

1. **Global module state.** Persistence still uses the module-global
   `_vitals_store` (`src/vitals_state.py`, a `dict`). (Partial mitigation:
   `src.dependencies.get_vitals_repo()` exposes a repository port for new code;
   test fixtures reset the shared dict.) **[partially mitigated]**
2. **Window anchor.** The windowing *engine* supports both `"oldest"` and
   `"recent"`; v1 pinned `"oldest"` (oldest-record anchor). v0.9.1 service
   uses `"recent"`. **[retired by v0.9.1]**
3. **Flat-line extrapolation by default.** A single window has no trend history,
   so the per-channel slope defaults to `0.0` and the forecast is flat; trend is
   only applied when ≥2 prior windows exist. **[current behaviour; mitigated
   when history exists]**
4. **No unit normalization.** `parse_observation` preserves `valueQuantity.unit`
   and validates it against an accepted set (§9.2); there is no cross-system
   conversion (°F ↔ °C). **[unit validation added v0.9.1; no conversion]**
5. **Lexicographic timestamp sorting.** Records are sorted by string compare of
   `timestamp`; mixed timezone offset representations can sort incorrectly.
   **[still applies]**
6. **`avpu` reachability.** AVPU is resolvable via SNOMED CT `valueCodeableConcept`
   (§9.1); numeric channels never carry it. **[reached via ingestion v0.9.1]**
7. **NEWS2-inspired, not NEWS2.** Thresholds loosely follow NEWS2 but are not
   the exact NEWS2 scale. **[still applies]**
8. **Single-observation window bias.** With one observation the window equals that
   single point (no averaging). **[still applies]**

---

## 7. Observability Surface

Counters (label-free — patient_id never appears as a label):
`vitals_ingested_total`, `forecasts_generated_total`,
`assessments_total`, `mcp_tool_calls_total`.

Histograms: `forecast_duration_seconds`, `ingest_duration_seconds`.

`/metrics` exposes the full Prometheus exposition via `generate_latest()`.

---

## 8. Phase 0/v0.9.1 Verification Matrix

| Criterion | How validated |
|---|---|
| v2 core & adapters | `src/core`, `src/ports`, `src/adapters` (strict). |
| Baseline behaviour | `docs/BASELINE.md` (this file). |
| Tests pass | `pytest` (markers `unit`/`contract`/`integration`/`e2e`/`property` registered via `pytest.ini`). |
| Coverage ≥ 80% on `src/` | `pytest --cov=src --cov-fail-under=80`. |
| `ruff` clean | `ruff check src/ tests/`. |
| `mypy` clean | `python -m mypy src/` (scoped overrides for `src/config`, `src/observability`, `src/main` in `pyproject.toml`). |

---

## 9. Phase Refinements (v0.9.x)

Behavior changes introduced after the Phase 0 baseline that are now part of the
v0.9.1 contract:

### 9.1 Consciousness (AVPU) through the ingest pipeline
- `parse_observation` now resolves a FHIR R4 `valueCodeableConcept` against a
  SNOMED CT code map (`248234008`→A Alert, `300202002`→V Voice, `450847002`→P
  Pain, `422768004`→U Unresponsive) and falls back to `display` text. The
  resolved letter is emitted on both `value` and `avpu`, so an AVPU observation
  flows through the same window/trend path as numeric vitals.
- `VitalSignsWindow.avpu` is therefore reachable via normal ingestion (retires
  BASELINE §6 #6). The DDS engine scores `avpu != "A"` at 3 and propagates
  `altered_consciousness_{A|V|P|U}` factors.

### 9.2 Unit validation at parse time
- `parse_observation` validates `valueQuantity.unit` against an accepted set
  per vital type (heart_rate: `bpm`/`beats/min`; blood_pressure: `mmHg`/`mm
  Hg`; spo2: `%`/`percent`; respiratory_rate: `breaths/min`/`rpm`;
  temperature: `°C`/`celsius`). Out-of-set units (e.g. `°F`, `kg`, `mm[Hg]`
  without space) emit `WARNING ... Non-standard unit ... dropping` and the
  observation is excluded from the parse result (retires BASELINE §6 #4 for the
  supported vitals). `valueCodeableConcept`/`valueString` observations carry no
  `unit` and are never rejected.

### 9.3 Domain bounds live in the model, not pydantic `Field` constraints
- The physiological caps (heart_rate/systolic_bp ∈ [0,300], diastolic_bp ∈
  [0,200], spo2 ∈ [0,100], respiratory_rate ∈ [0,60], temperature ∈ [30,45])
  are now expressed as `CLINICAL_BOUNDS` constants in
  `src/core/domain/vitals.py` and applied by `clamp()` at construction and
  serialization — there are **no** `Field(ge=, le=)` validators on
  `VitalSignsWindow`. A projection with an out-of-range value (e.g.
  `heart_rate=350`) constructs successfully and is clamped downstream by the
  SafetyShell, rather than raising `ValidationError` (retires BASELINE §4's
  "Field ge/le" interpretation and §6 #3).

### 9.4 SafetyShell immutability + clamp
- `src/core/safety/`: `SafetyShell.validate` is a pure function of
  `(ForecastResult, VitalSignsWindow)` — it builds a **copy** and never mutates
  the caller's `ForecastResult`, its nested
  `forecasted_vitals`/`uncertainty_lower`/`uncertainty_upper` windows, or
  `contributing_factors`. The returned forecasted and bounds values are clamped
  to `CLINICAL_BOUNDS`; `uncertainty_upper < forecasted` on a field is
  re-anchored to the forecasted value (the upper bound must envelope the point
  estimate).

### 9.5 Episode `available_vitals`
- `available_vitals` on an `Episode` is derived **only** from the observed
  `VitalSignsWindow` (the seven numeric fields plus `avpu`) — it is never
  overwritten from assessment `contributing_factors`, which include scoring
  artifacts such as `heart_rate_critical`. `discover_channels` returns this
  list and is safe to call after `transition`.

### 9.6 DDS severity tiers
- Tier boundaries (see `src/core/governance/severity.py`, mirrored in
  `manifests/mcp.json` and `manifests/SKILL.md`):
  `NORMAL` 0–2, `WARNING` 3–4, `ALERT` 5–6, `EMERGENCY` ≥7.
  Risk tiers exposed by the baseline are `NORMAL/WARNING/ALERT/EMERGENCY`
  (consistent with §5.5).

### 9.7 Version source
- `app_version` is read dynamically from installed package metadata in
  `src/config.py` (`importlib.metadata.version("icu_vitals_transformer")`),
  defaulting to `0.0.0` when metadata is unavailable; both manifests
  (`manifests/mcp.json`, `manifests/SKILL.md`) carry `0.9.0`.

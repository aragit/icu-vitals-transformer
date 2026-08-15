# BASELINE.md — ICU Vitals Transformer (Pre-Refactor)

This document locks down the **current behavioral contract** of the
`icu-vitals-transformer` repository as of the Phase 0 baseline. It is the
source of truth that the Phase 0 backfilled test suite asserts against. Any
deviation from these behaviors, unless explicitly called out as a
refactoring objective, is a regression.

> **Scope rule (Phase 0):** No production code under `src/` is modified.
> This document describes `src/` exactly as it exists at baseline. The
> "Legacy Limitations" section lists intentional defects/assumptions that
> later phases are expected to refactor; the test suite asserts the
> *current* (baseline) behavior, including these limitations, so that
> refactors can confidently preserve behavior and remove the limitations one
> at a time.

---

## 1. Architecture Overview

```
HTTP clients / local agents
   │
   ├──► FastAPI app            (src/main.py)
   │        └─ /health, /metrics
   │        └─ /vitals/*         (src/api/routes/vitals.py)
   │
   └──► MCP Server (stdio)       (src/mcp_server/server.py)
            tools: ingest_vitals, get_forecast, get_deterioration_index

Shared in-memory state:
   src/mcp_server/server.py  →  _vitals_store: dict[str, list[dict]]
   (FastAPI routes import & mutate the SAME global store.)
```

### Request lifecycle (current)
1. A FHIR R4 `Observation` (or batch) enters either `/vitals/ingest`
   (HTTP) or the `ingest_vitals` MCP tool.
2. `src.ingestion.fhir_parser.parse_batch` → `parse_observation`
   reduces each Observation to a flat record:
   `{patient_id, vital_type, value, timestamp, unit}`.
3. Records are appended to the module-global `_vitals_store[patient_id]`,
   then `src.ingestion.windowing.window_vitals(records, patient_id)`
   aggregates them into a `VitalSignsWindow`.
4. `src.forecasting.ensemble.ensemble_forecast(window)` produces three
   `ForecastResult` objects (horizons 60, 240, 720 min) using the
   `DeterministicBackend` (`src.forecasting.forecaster.forecast_vitals`).
5. `src.forecasting.ensemble.ensemble_deterioration_index(forecasts)`
   collapses the multi-horizon results into one weighted
   `DeteriorationAssessment`.

### Component map
| Concern | Module | Notes |
|---|---|---|
| Config | `src/config.py` | `pydantic-settings` `Settings`; defaults: port 8000, horizons 60/240/720. |
| Ingestion | `src/ingestion/fhir_parser.py` | LOINC → vital_type map (6 codes). |
| Windowing | `src/ingestion/windowing.py` | 5-minute sliding window from oldest record. |
| Forecast | `src/forecasting/forecaster.py` | Linear trend extrapolation + clinical clamping. |
| Backends | `src/forecasting/backends.py` | `ForecastBackend` protocol + `DeterministicBackend`. |
| Ensemble | `src/forecasting/ensemble.py` | Horizon weights 60:0.5, 240:0.3, 720:0.2. |
| Governance | `src/governance/deterioration.py`, `severity.py` | NEWS2-inspired scoring. |
| Models | `src/models/{vitals,forecast,mcp}.py` | Pydantic BaseModel contracts. |
| Observability | `src/observability/metrics.py` | Prometheus counters/histograms. |
| MCP | `src/mcp_server/{server,stdio}.py` | stdio transport entry point. |

---

## 2. REST API (FastAPI) — Active Routes

The application is created in `src/main.py`. Routers are mounted under
`/vitals`, `/health`, `/metrics`.

### `GET /`
Root/landing endpoint.
- Response `200`:
  ```json
  { "name": "icu-vitals-transformer", "version": "0.1.0", "status": "operational" }
  ```

### `GET /health/`
Liveness probe.
- Response `200`:
  ```json
  { "status": "healthy", "service": "icu-vitals-transformer", "version": "0.1.0" }
  ```

### `GET /health/ready`
Readiness probe.
- Response `200`:
  ```json
  { "status": "ready", "service": "icu-vitals-transformer", "version": "0.1.0" }
  ```

### `GET /metrics/`
Prometheus exposition endpoint backed by `prometheus_client.generate_latest()`.
- Response `200`, media-type `text/plain; version=0.0.4`.

### `POST /vitals/ingest`
Ingest a batch of FHIR R4 Observations and return the windowed result.
- Request body (`VitalIngestionRequest`):
  ```json
  { "observations": [ { ...FHIR Observation... } ] }
  ```
- Behavior: `parse_batch(observations)` → 400 "No valid observations parsed"
  if empty; otherwise append to `_vitals_store[patient_id]` and return
  `window_vitals(parsed, patient_id)` → 400 "Could not window vitals" if `None`.
  `patient_id` is taken from `parsed[0]["patient_id"]` (defaults to `unknown`).
- Response `200` → `VitalSignsWindow` JSON.

### `GET /vitals/current/{patient_id}`
Return the latest windowed vitals for a patient.
- 404 if no records for `patient_id`; 400 if windowing yields no valid window.
- Response `200` → `VitalSignsWindow` JSON.

### `GET /vitals/forecast/{patient_id}`
Return the multi-horizon forecast for a patient.
- 404 if no records; 400 if windowing yields no valid window.
- Response `200` → `list[ForecastResult]` (exactly 3 elements: 60, 240, 720 min).

### `GET /vitals/deterioration/{patient_id}`
Return the ensemble deterioration assessment for a patient.
- 404 if no records; 400 if windowing yields no valid window.
- Response `200` → `DeteriorationAssessment` JSON.

---

## 3. MCP Server Tools — Active Definitions

Defined in `src/mcp_server/server.py`. The three tools are exposed via the
`list_tools` handler; invocation is routed by `call_tool`.

### `ingest_vitals`
- Schema: `src.models.mcp.IngestVitalsInput` →
  `{ patient_id: str, observations: list[dict] }`.
- Behavior: parse batch, store into `_vitals_store`, window and return the
  `VitalSignsWindow` (JSON-serialized). On failure returns a JSON error:
  `{"error": "No valid observations parsed"}` or
  `{"error": "Could not window vitals"}`.

### `get_forecast`
- Schema: `src.models.mcp.GetForecastInput` →
  `{ patient_id: str, horizon_minutes: int (60..720, default 60) }`.
- Behavior: window stored records, run `ensemble_forecast`, return the
  `ForecastResult` whose `horizon_minutes` matches the requested one.
- Errors: `{"error": "No vitals stored for {patient_id}"}`,
  `{"error": "Could not window vitals"}`,
  `{"error": "Horizon {horizon} not available"}`.

### `get_deterioration_index`
- Schema: `src.models.mcp.GetDeteriorationInput` → `{ patient_id: str }`.
- Behavior: window stored records, run `ensemble_forecast` then
  `ensemble_deterioration_index`; return the `DeteriorationAssessment`
  (JSON-serialized). Errors mirror `get_forecast`.

### Transport entry point
`src/mcp_server/stdio.py` runs `mcp.server.stdio` over stdio. Invoked via
`python -m src.mcp_server.stdio`.

---

## 4. Data Contracts (Models)

### `VitalSignsWindow` (`src/models/vitals.py`)
```
patient_id: str
window_start, window_end: datetime
heart_rate, systolic_bp, diastolic_bp, spo2, respiratory_rate, temperature:
    Optional[float]  (clamped via Field ge/le constraints)
avpu: Optional[str]   (pattern ^[AVPU]$)
```
Constraints enforced: heart_rate/systolic_bp ∈ [0,300]; diastolic_bp ∈ [0,200];
spo2 ∈ [0,100]; respiratory_rate ∈ [0,60]; temperature ∈ [30,45].

### `ForecastResult` (`src/models/forecast.py`)
```
patient_id: str
horizon_minutes: int   [60..720]
forecasted_vitals, uncertainty_lower, uncertainty_upper: VitalSignsWindow
deterioration_index: float  [0..20]
severity: str   ^(NORMAL|WARNING|ALERT|EMERGENCY)$
generated_at: datetime  (tz-aware UTC at generation)
```

### `DeteriorationAssessment` (`src/models/forecast.py`)
```
patient_id: str
ensemble_score: float  [0..20]
severity: str   ^(NORMAL|WARNING|ALERT|EMERGENCY)$
contributing_factors: list[str]
assessed_at: datetime
```

---

## 5. Core Algorithms (Baseline Behavior)

### 5.1 FHIR parsing — `parse_observation`
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

### 5.2 Windowing — `window_vitals`
- Empty input → `None`.
- Filters records by `patient_id`; if none for patient → `None`.
- **Sorts records by `timestamp` as a lexicographic string** (not parsed
  datetime). For ISO-8601 UTC strings this is equivalent; mixed offset
  formats can sort incorrectly (see Limitations).
- `window_start = oldest.timestamp`; `window_end = window_start + 5 min`
  (default `window_minutes=5`).
- Only records with `timestamp <= window_end` are included.
- Aggregates each vital type by **mean** (rounded to 2 dp).
- Non-numeric values are logged and skipped (excluded from mean).
- `avpu` is **not aggregated** — the returned window always has `avpu=None`.

### 5.3 Forecasting — `forecast_vitals`
- Flat linear extrapolation:
  `extrapolated = current + trend_per_hour * (horizon_minutes / 60)`.
- **Default `trend_per_hour` is `0.0` for every field** → flat-line
  extrapolation (forecast == current within that horizon).
- Each extrapolated value is **clamped** to clinical bounds:
  heart_rate/systolic_bp ∈ [0,300], diastolic_bp ∈ [0,200], spo2 ∈ [0,100],
  respiratory_rate ∈ [0,60], temperature ∈ [30,45].
- `None` channels stay `None` (no imputation).
- Uncertainty bounds: `uncertainty(h) = 2.0 * (1 + 0.1 * h/60)`;
  lower = `clamp(extrapolate - uncertainty)`, upper = `clamp(...) + uncertainty`.
  Bounds grow with horizon (1h≈2.2, 4h≈2.8, 12h≈4.4).
- `deterioration_index` initialized to `0.0` and `severity` to `"NORMAL"`;
  the **ensemble layer overwrites** these.

### 5.4 Ensemble — `ensemble_forecast` / `ensemble_deterioration_index`
- Generates forecasts at horizons `[60, 240, 720]`.
- For each horizon, computes `compute_deterioration_index` and
  `severity_from_score`, overwriting the placeholders above.
- `HORIZON_WEIGHTS = {60: 0.5, 240: 0.3, 720: 0.2}` (sum to 1.0).
- `ensemble_deterioration_index` returns the weighted mean of per-horizon
  `deterioration_index`, the **max** severity tier across horizons, and a
  de-duplicated list of contributing factors (order: first appearance).

### 5.5 Governance — scoring
- `compute_deterioration_index(vitals, trend="stable")` → `(score, factors)`.
- NEWS2-inspired per-vital scoring (see `src/governance/deterioration.py`):
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
  *(The epic's LOW/MEDIUM/HIGH/CRITICAL naming is the future-state target
  during the governance refactor; the baseline emits the four tiers above.)*

---

## 6. Legacy Limitations (refactor targets)

These are intentional baseline constraints that Phase 0 tests assert, and
that later phases are designed to remove:

1. **Global module state.** All persistence lives in the module-global
   `src/mcp_server/server.py:_vitals_store`. FastAPI routes (`vitals.py`)
   import and mutate this same dict directly. There is no per-request
   isolation, no persistence, and reset on process restart.
2. **Window anchor = oldest record.** `window_vitals` anchors its 5-minute
   window on `patient_records[0]` (the oldest timestamp after sorting)
   rather than on the **most recent** observation. This means a patient's
   "current window" reflects a trailing slice anchored in the past.
3. **Flat-line extrapolation by default.** With `trend_per_hour` defaulting
   to `0.0` everywhere, `forecast_vitals` is a no-op extrapolation
   (forecast == current). Trend is never computed from prior windows.
4. **No unit normalization.** `parse_observation` preserves whatever
   `valueQuantity.unit` string arrives (e.g. `"bpm"`, `"mmHg"`); there is no
   conversion between unit systems (e.g. °F ↔ °C) or rejection of
   non-standard units.
5. **Lexicographic timestamp sorting.** Records are sorted by string compare
   of `timestamp`. Mixed timezone offset representations
   (`Z` vs `+00:00`, or non-UTC offsets) can sort incorrectly.
6. **`avpu` is never populated by the ingest/window pipeline.** No LOINC
   code maps to consciousness, so `VitalSignsWindow.avpu` is always `None`
   unless set directly on the model. The deterioration engine's AVPU
   branch is therefore unreachable through normal ingestion.
7. **NEWS2-inspired, not NEWS2.** Thresholds loosely follow NEWS2 but are
   not the exact NEWS2 scale (e.g. the AVPU score and some cut points
   differ). Documented as the baseline contract.
8. **Single-observation window bias.** Because the window is anchored on
   the oldest record with a 5-minute span, a single observation yields a
   window equal to that one point (no averaging possible).

---

## 7. Observability Surface (Baseline)

Counters (label-free, by design — patient_id never appears as a label):
`vitals_ingested_total`, `forecasts_generated_total`,
`assessments_total`, `mcp_tool_calls_total`.

Histograms: `forecast_latency_seconds`, `ingest_duration_seconds`,
`forecast_duration_seconds`.

`/metrics` exposes the full Prometheus exposition via `generate_latest()`.

---

## 8. Phase 0 Verification Matrix

| Criterion | How validated |
|---|---|
| `src/` untouched | `git diff --stat` shows no `src/` entries. |
| Baseline behavior | `docs/BASELINE.md` (this file). |
| Tests pass | `pytest` (all markers registered via `pytest.ini`). |
| Coverage ≥ 80% on `src/` | `pytest --cov=src --cov-fail-under=80`. |
| `ruff` clean | `ruff check src/ tests/`. |
| `mypy` clean | `mypy src/` (see mypy baseline-lock overrides in `pyproject.toml`). |

---

## 9. Phase Refinements (v0.9.0)

Behavior changes introduced between the Phase 0 baseline and the v0.9.0
release. Tests for each live under `tests/unit/` and `tests/integration/`.

### 9.1 Consciousness (AVPU) through the ingest pipeline
- `parse_observation` now resolves a FHIR R4 `valueCodeableConcept` against a
  SNOMED CT code map (`248234008`→A Alert, `300202002`→V Voice, `450847002`→P
  Pain, `422768004`→U Unresponsive) and falls back to `display` text. The
  resolved letter is emitted on **both** `value` and `avpu`, so an AVPU
  observation reuses any LOINC (e.g. `8867-4`) and flows through the same
  window/trend path as numeric vitals.
- `VitalSignsWindow.avpu` is therefore reachable via normal ingestion
  (retires BASELINE §6 #6). `compute_deterioration_index` scores
  `avpu != "A"` at 3 and the engine propagates it to the DDS forecast and
  `altered_consciousness_{A|V|P|U}` factors.
- `update_vitals` in `src/core/windowing/engine.py:100` captures the latest
  `avpu` across the window (last non-empty wins) and aggregates numeric
  channels via mean, so a window mixing a quantity and an AVPU observation on
  the same LOINC keeps both signals.

### 9.2 Unit validation at parse time
- `parse_observation` validates `valueQuantity.unit` against an accepted set
  per vital type (heart_rate: `bpm`/`beats/min`; blood_pressure: `mmHg`/`mm
  Hg`; spo2: `%`/`percent`; respiratory_rate: `breaths/min`/`rpm`;
  temperature: `°C`/`celsius`). Out-of-set units (e.g. `°F`, `kg`, `mm[Hg]`
  without space) emit
  `WARNING ... Non-standard unit ... dropping` and the observation is
  excluded from the parse result (retires BASELINE §6 #4 for the
  supported vitals). `valueCodeableConcept`/`valueString` observations carry
  no `unit` and are never rejected.

### 9.3 Domain bounds live in the model, not pydantic `Field` constraints
- The physiological caps (heart_rate/systolic_bp ∈ [0,300], diastolic_bp ∈
  [0,200], spo2 ∈ [0,100], respiratory_rate ∈ [0,60], temperature ∈ [30,45])
  are now expressed as `CLINICAL_BOUNDS` constants in
  `src/core/domain/vitals.py` and applied by `clamp()` at construction and
  serialization — there are **no** `Field(ge=, le=)` validators on
  `VitalSignsWindow`. A projection with an out-of-range value (e.g.
  `heart_rate=350`) constructs successfully and is clamped downstream by the
  SafetyShell, rather than raising `ValidationError` (retires BASELINE §6
  #3's validator-as-bound interpretation).

### 9.4 SafetyShell immutability + clamp
- `SafetyShell.validate` is a pure function of `(ForecastResult, VitalSignsWindow)`:
  it builds a **copy** and never mutates the caller's `ForecastResult`, its
  nested `forecasted_vitals`/`uncertainty_lower`/`uncertainty_upper` windows,
  or `contributing_factors`. The returned forecasted and bounds values are
  clamped to `CLINICAL_BOUNDS`; `uncertainty_upper < forecasted` on a field is
  re-anchored to the forecasted value (the upper bound must envelope the
  point estimate).

### 9.5 Episode `available_vitals`
- `available_vitals` on an `Episode` is derived **only** from the observed
  `VitalSignsWindow` (the seven numeric fields plus `avpu`) — it is never
  overwritten from assessment `contributing_factors`, which include
  scoring artifacts such as `heart_rate_critical`. `discover_channels`
  returns this list and is safe to call after `transition`.

### 9.6 DDS severity tiers
- Tier boundaries (see `src/governance/severity.py`,
  mirrored in `manifests/mcp.json` and `manifests/SKILL.md`):
  `NORMAL` 0–2, `WARNING` 3–4, `ALERT` 5–6, `EMERGENCY` ≥7.
  Risk tiers exposed by the baseline are `NORMAL/WARNING/ALERT/EMERGENCY`
  (consistent with BASELINE §5.5).

### 9.7 Version source
- `app_version` is read dynamically from installed package metadata in
  `src/config.py` (`importlib.metadata.version("icu_vitals_transformer")`),
  defaulting to `0.0.0` when metadata is unavailable; both manifests
  (`manifests/mcp.json`, `manifests/SKILL.md`) carry `0.9.0`.

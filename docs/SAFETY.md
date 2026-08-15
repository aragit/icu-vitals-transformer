# Safety Specification — `SafetyShell`

`src/core/safety/shell.py` implements the **SafetyShell** decorator — a
mandatory, fail-closed invariant gate around every `ForecastBackend`. It is the
last transformation before a `ForecastResult` is returned to any adapter.

## 1. Purpose

The deterministic forecaster can, under aggressive trends, project values that
exceed physiological plausibility. `SafetyShell` guarantees three invariants
on **every** outbound forecast:

1. **Bounded physiology** — no projected vital exceeds the clinical hard bounds
   in `src/core/forecasting/forecaster.py::BOUNDS`.
2. **Valid uncertainty envelope** — `uncertainty_lower ≤ forecasted ≤
   uncertainty_upper` per channel.
3. **Stale-data transparency** — windows older than `STALE_DATA_THRESHOLD_SECONDS`
   (300 s) set `ForecastResult.stale_data_warning = True` and append
   `"stale_data_warning"` to `contributing_factors`.

## 2. Safety Algorithm

```
forecast = backend.forecast(window, horizon, trend_per_hour)   # may raise
   │  (on any exception: flat-line fallback to forecast_vitals(window, h, {}))
   ↓
forecasted_vitals     = clamp_window(backend_result.forecasted_vitals)
uncertainty_lower     = clamp_window(backend_result.uncertainty_lower)
uncertainty_upper     = clamp_window(backend_result.uncertainty_upper)
for each numeric field:
    lower = min(lower, forecasted)   # enforce lower ≤ forecasted
    upper = max(upper, forecasted)   # enforce forecasted ≤ upper
if data_freshness_seconds > 300:
    stale_data_warning = True
    contributing_factors += ["stale_data_warning"]
return ForecastResult(...)
```

`clamp_window` applies `BOUNDS` per field and preserves the Phase 0
truthiness semantics: a falsy (`None`/`0.0`) channel yields `None` bounds so
downstream clients cannot misinterpret a zero vital as a valid projection.

## 3. Clinical Bounds (clamped by SafetyShell)

| Vital | Min | Max |
|-------|-----|-----|
| heart_rate | 0.0 | 300.0 |
| systolic_bp | 0.0 | 300.0 |
| diastolic_bp | 0.0 | 200.0 |
| spo2 | 0.0 | 100.0 |
| respiratory_rate | 0.0 | 60.0 |
| temperature | 30.0 | 45.0 |

## 4. DDS Range Guarantee

`compute_dds` returns `0 ≤ score ≤ 20` (`DDS_MAX_SCORE`). `assess_episode`
further clamps the exposed `dds_score` to `min(score, 20.0)`. Severity
tiers (`src/core/governance/severity.py::severity_from_score`, mirrored on
`src/core/domain/episode.py::EpisodeState`):

| Tier | DDS range |
|------|-----------|
| NORMAL | 0–2 |
| WARNING | 3–4 |
| ALERT | 5–6 |
| EMERGENCY | ≥7 |

`CRITICAL` is not an automated DDS tier — it is reserved for a future manual
clinician override and is never emitted by `severity_from_score`.

## 5. Fail-Closed Fallback

If the wrapped `ForecastBackend` raises, `SafetyShell` catches the exception,
logs at `CRITICAL`, increments the `safety_shell_fallback_total` counter (via
the adapter-wired `on_fallback` hook), and recomputes a **flat-line** forecast
from the current window with no trend. The caller always receives a
`ForecastResult` that satisfies all three invariants above.

> **Design note:** DDS loosely follows NEWS2 cut points but is **not** standard
> NEWS2 — some thresholds and AVPU weighting deviate.

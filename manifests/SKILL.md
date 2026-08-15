# Agent Skill: ICU Vitals Transformer (Clinical Forecasting)

This skill exposes ICU vital-sign trend forecasting, SafetyShell-bounded
extrapolation, and Deterministic Deterioration Score (DDS) assessment via the
MCP and REST v2 transports.

## Safety Boundary

> This tool is an **informational skill engine**. It never initiates direct
> clinical intervention, does not replace bedside monitoring, and every payload
> carries a `_meta.clinical_disclaimer`:
> *"This output is informational only. Not FDA/CE marked. Must be reviewed by a
> qualified clinician before any action."*

All forecasts are **deterministic** (`_meta.determinism: "deterministic"`) and
the tool surface reports **no side effects** (`_meta.side_effects: false`). The
pure-Python core applies physiological clamping through `SafetyShell` so projected
values never exceed safe bounds.

## Workflow Guidance

| Situation | Invoke |
| --- | --- |
| A patient has vitals to assess and **no explicit episode** is known | Call `ingest_vitals` first — it auto-resolves or creates the active episode (`discover_episode` is then optional). |
| A patient is **known to have multiple active episodes** | Call `discover_episode` **before** forecasting to disambiguate; provide an explicit `episode_id`. |
| Trend / uncertainty forecast is needed | Call `get_forecast` with `horizon_minutes` (60–720). |
| Severity / risk tier is needed | Call `get_deterioration_index`; it records the episode state transition. |

When `episode_id` is omitted and more than one active episode exists for the
patient, the server returns an `episodes` array listing every active episode
(with `episode_id`, `state`, `created_at`) so the caller can select one — it
never guesses silently.

## DDS Risk Tier Interpretations

| Tier | DDS range | Meaning |
| --- | --- | --- |
| `NORMAL` | 0–2 | No immediate physiological concern. |
| `WARNING` | 3–4 | Mild derangement; trend monitoring warranted. |
| `ALERT` | 5–6 | Significant physiology drift; escalate review. |
| `EMERGENCY` | ≥7 | Critical thresholds exceeded; treat as urgent. |

> Note: DDS loosely follows NEWS2 cut points but is **not** the standard NEWS2
> scale; some thresholds and AVPU weighting differ. `CRITICAL` is an episode
> lifecycle state (`EpisodeState.CRITICAL`), not a DDS severity tier — there is
> no DDS score range that maps to `CRITICAL`.

## Resource Discovery

- `GET /discover` — server capability matrix (tools, transports, resources, version).
- MCP resources: `clinical://bounds/v1`, `clinical://loinc-mapping/v1`,
  `clinical://dds-tiers/v1`.

## Auth

CIMD/JWT bearer tokens carry `iss`, `sub`, and `roles`; the `sub` (`requested_by`)
principal is recorded in audit logs alongside `correlation_id`. Unauthenticated
mode is permitted for local dev (`MCP_TRANSPORT=stdio` / `DEBUG=true`).

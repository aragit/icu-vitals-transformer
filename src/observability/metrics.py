"""Prometheus metrics for ICU Vitals Transformer (observability adapter).

Privacy & cardinality contract: counters and gauges are intentionally
label-free or carry only low-cardinality non-identifying labels (e.g. ``state``
tiers). No metric exposes identifiers of individual patients or episodes —
identifying fields travel only in structured logs, never in metric labels.

Backward-compat aliases (``VITALS_INGESTED``, ``FORECASTS_GENERATED``) are
retained so the Phase 0 metric contract and its tests keep passing; the new
Phase 4 names (``VITALS_INGESTED_TOTAL``, ``FORECASTS_GENERATED_TOTAL``) are
bound to the same counters.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

# Counters — no labels to prevent cardinality explosion.
VITALS_INGESTED = Counter(
    "vitals_ingested_total",
    "Total number of FHIR observations successfully ingested",
)

FORECASTS_GENERATED = Counter(
    "forecasts_generated_total",
    "Total number of forecast ensembles generated",
)

ASSESSMENTS_TOTAL = Counter(
    "assessments_total",
    "Total number of deterioration assessments performed",
)

MCP_TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Total number of MCP tool invocations",
)

SAFETY_SHELL_FALLBACK_TOTAL = Counter(
    "safety_shell_fallback_total",
    "Total number of safety shell invariant fallbacks triggered",
)

STALE_DATA_WARNING_TOTAL = Counter(
    "stale_data_warning_total",
    "Total number of stale-data warnings surfaced by the safety shell",
)

# Phase 4 canonical names (aliased to the same metric objects).
VITALS_INGESTED_TOTAL = VITALS_INGESTED
FORECASTS_GENERATED_TOTAL = FORECASTS_GENERATED

# Gauges — only the episode risk tier is labelled (no identifiers).
EPISODE_STATE_GAUGE = Gauge(
    "active_episodes",
    "Active episodes count by state",
    labelnames=["state"],
)


def set_episode_state_gauges(counts: dict[str, int]) -> None:
    """Update the per-state episode gauge from a ``{state: count}`` mapping.

    Any stale tiers are reset to zero so the gauge reflects the live set of
    states (NORMAL/WARNING/ALERT/EMERGENCY/CRITICAL).
    """
    tiers = ("NORMAL", "WARNING", "ALERT", "EMERGENCY", "CRITICAL")
    for tier in tiers:
        EPISODE_STATE_GAUGE.labels(state=tier).set(counts.get(tier, 0))


# Histograms
FORECAST_LATENCY = Histogram(
    "forecast_latency_seconds",
    "Time spent generating individual forecast",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

INGEST_DURATION = Histogram(
    "ingest_duration_seconds",
    "Time spent parsing and ingesting observations",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

FORECAST_DURATION = Histogram(
    "forecast_duration_seconds",
    "Time spent generating forecast ensemble",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)


def metrics_handler() -> bytes:
    """Return Prometheus exposition format."""
    return generate_latest()


__all__ = [
    "VITALS_INGESTED",
    "FORECASTS_GENERATED",
    "ASSESSMENTS_TOTAL",
    "MCP_TOOL_CALLS",
    "SAFETY_SHELL_FALLBACK_TOTAL",
    "STALE_DATA_WARNING_TOTAL",
    "VITALS_INGESTED_TOTAL",
    "FORECASTS_GENERATED_TOTAL",
    "EPISODE_STATE_GAUGE",
    "set_episode_state_gauges",
    "FORECAST_LATENCY",
    "INGEST_DURATION",
    "FORECAST_DURATION",
    "metrics_handler",
]

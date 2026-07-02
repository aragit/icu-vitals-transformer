"""Prometheus metrics for ICU Vitals Transformer.

All counters are intentionally label-free to avoid high-cardinality issues
with patient_id in production. Labels are passed as structured log fields.
"""

from prometheus_client import Counter, Histogram, generate_latest

# Counters — no labels to prevent cardinality explosion
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


def metrics_handler():
    """Return Prometheus exposition format."""
    return generate_latest()

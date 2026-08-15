"""Tests for Prometheus metrics."""

import pytest

from src.observability.metrics import (
    ASSESSMENTS_TOTAL,
    FORECAST_DURATION,
    FORECASTS_GENERATED,
    INGEST_DURATION,
    MCP_TOOL_CALLS,
    STALE_DATA_WARNING_TOTAL,
    VITALS_INGESTED,
    metrics_handler,
)


class TestMetrics:
    """Test metric counters, histograms and exposition."""

    def setup_method(self):
        """Reset counters/histograms before each test."""
        VITALS_INGESTED._value.set(0)
        FORECASTS_GENERATED._value.set(0)
        ASSESSMENTS_TOTAL._value.set(0)
        MCP_TOOL_CALLS._value.set(0)
        STALE_DATA_WARNING_TOTAL._value.set(0)
        INGEST_DURATION._sum.set(0.0)
        FORECAST_DURATION._sum.set(0.0)

    def test_vitals_ingested_counter(self):
        """VITALS_INGESTED increments correctly."""
        before = VITALS_INGESTED._value.get()
        VITALS_INGESTED.inc(5)
        after = VITALS_INGESTED._value.get()
        assert after == before + 5

    def test_forecasts_generated_counter(self):
        """FORECASTS_GENERATED increments correctly."""
        before = FORECASTS_GENERATED._value.get()
        FORECASTS_GENERATED.inc(3)
        after = FORECASTS_GENERATED._value.get()
        assert after == before + 3

    def test_assessments_counter(self):
        """ASSESSMENTS_TOTAL increments correctly."""
        before = ASSESSMENTS_TOTAL._value.get()
        ASSESSMENTS_TOTAL.inc()
        after = ASSESSMENTS_TOTAL._value.get()
        assert after == before + 1

    def test_mcp_tool_calls_counter(self):
        """MCP_TOOL_CALLS increments correctly."""
        before = MCP_TOOL_CALLS._value.get()
        MCP_TOOL_CALLS.inc(2)
        after = MCP_TOOL_CALLS._value.get()
        assert after == before + 2

    def test_stale_data_warning_counter(self):
        """STALE_DATA_WARNING_TOTAL increments correctly."""
        before = STALE_DATA_WARNING_TOTAL._value.get()
        STALE_DATA_WARNING_TOTAL.inc()
        after = STALE_DATA_WARNING_TOTAL._value.get()
        assert after == before + 1

    def test_metrics_handler_returns_bytes(self):
        """metrics_handler returns Prometheus exposition format."""
        data = metrics_handler()
        assert isinstance(data, bytes)
        assert b"vitals_ingested_total" in data
        assert b"forecasts_generated_total" in data
        assert b"assessments_total" in data
        assert b"mcp_tool_calls_total" in data
        assert b"stale_data_warning_total" in data

    def test_counter_cannot_decrement(self):
        """Counters reject negative increments."""
        with pytest.raises(ValueError, match="non-negative"):
            VITALS_INGESTED.inc(-1)

    def test_histograms_registered(self):
        """INGEST_DURATION and FORECAST_DURATION histograms are exported."""
        assert INGEST_DURATION._name == "ingest_duration_seconds"
        assert FORECAST_DURATION._name == "forecast_duration_seconds"

    def test_histograms_observe(self):
        """Histograms record observed durations."""
        before = INGEST_DURATION._sum.get()
        INGEST_DURATION.observe(0.123)
        assert INGEST_DURATION._sum.get() == before + 0.123

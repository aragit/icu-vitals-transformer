"""Tests for Prometheus metrics."""

import pytest

from src.observability.metrics import (
    VITALS_INGESTED,
    FORECASTS_GENERATED,
    ASSESSMENTS_TOTAL,
    MCP_TOOL_CALLS,
    metrics_handler,
)


class TestMetrics:
    """Test metric counters and exposition."""

    def setup_method(self):
        """Reset counters before each test."""
        VITALS_INGESTED._value.set(0)
        FORECASTS_GENERATED._value.set(0)
        ASSESSMENTS_TOTAL._value.set(0)
        MCP_TOOL_CALLS._value.set(0)

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

    def test_metrics_handler_returns_bytes(self):
        """metrics_handler returns Prometheus exposition format."""
        data = metrics_handler()
        assert isinstance(data, bytes)
        assert b"vitals_ingested_total" in data
        assert b"forecasts_generated_total" in data
        assert b"assessments_total" in data
        assert b"mcp_tool_calls_total" in data

    def test_counter_cannot_decrement(self):
        """Counters reject negative increments."""
        with pytest.raises(ValueError, match="non-negative"):
            VITALS_INGESTED.inc(-1)

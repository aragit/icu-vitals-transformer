"""Tests for Prometheus metrics."""

import pytest

from src.observability.metrics import (
    ASSESSMENTS_TOTAL,
    EPISODE_STATE_GAUGE,
    FORECASTS_GENERATED,
    MCP_TOOL_CALLS,
    STALE_DATA_WARNING_TOTAL,
    VITALS_INGESTED,
    metrics_handler,
    set_episode_state_gauges,
)

ALL_STATES = ("NORMAL", "WARNING", "ALERT", "EMERGENCY", "CRITICAL")


class TestMetrics:
    """Test metric counters and exposition."""

    def setup_method(self):
        """Reset counters before each test."""
        VITALS_INGESTED._value.set(0)
        FORECASTS_GENERATED._value.set(0)
        ASSESSMENTS_TOTAL._value.set(0)
        MCP_TOOL_CALLS._value.set(0)
        STALE_DATA_WARNING_TOTAL._value.set(0)
        set_episode_state_gauges({s: 0 for s in ALL_STATES})

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


class TestEpisodeStateGauge:
    """Tests for set_episode_state_gauges (Phase A.1)."""

    def test_two_normal_one_alert(self):
        """2 NORMAL + 1 ALERT episode → gauge labels reflect correct counts."""
        counts = {"NORMAL": 2, "ALERT": 1}
        set_episode_state_gauges(counts)
        assert EPISODE_STATE_GAUGE.labels(state="NORMAL")._value.get() == 2
        assert EPISODE_STATE_GAUGE.labels(state="ALERT")._value.get() == 1
        assert EPISODE_STATE_GAUGE.labels(state="WARNING")._value.get() == 0
        assert EPISODE_STATE_GAUGE.labels(state="EMERGENCY")._value.get() == 0
        assert EPISODE_STATE_GAUGE.labels(state="CRITICAL")._value.get() == 0

    def test_all_states_zero(self):
        """Empty counts reset all tiers to zero."""
        counts = {"NORMAL": 0, "WARNING": 0, "ALERT": 0, "EMERGENCY": 0, "CRITICAL": 0}
        set_episode_state_gauges(counts)
        for tier in ALL_STATES:
            assert EPISODE_STATE_GAUGE.labels(state=tier)._value.get() == 0

    def test_missing_tier_resets_to_zero(self):
        """Tiers absent from counts are reset to zero (stale reset)."""
        # First set some non-zero values.
        set_episode_state_gauges({"ALERT": 3, "EMERGENCY": 2})
        # Then only provide NORMAL — all others must drop to 0.
        set_episode_state_gauges({"NORMAL": 1})
        assert EPISODE_STATE_GAUGE.labels(state="NORMAL")._value.get() == 1
        assert EPISODE_STATE_GAUGE.labels(state="ALERT")._value.get() == 0
        assert EPISODE_STATE_GAUGE.labels(state="EMERGENCY")._value.get() == 0

    def test_histograms_registered(self):
        """INGEST_DURATION and FORECAST_DURATION histograms are exported."""
        from src.observability.metrics import FORECAST_DURATION, INGEST_DURATION

        assert INGEST_DURATION._name == "ingest_duration_seconds"
        assert FORECAST_DURATION._name == "forecast_duration_seconds"

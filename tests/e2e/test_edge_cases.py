"""Phase 5 edge-case & adverse-condition matrix.

Covers temporal clock-skew tolerance, out-of-order ingestion, extreme
boundary values, rate-of-change spikes, and data-staleness propagation across
the REST v2 and MCP transports.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.factories import make_fhir_obs

pytestmark = pytest.mark.e2e

_PT = "http://test"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload(result: object) -> dict:
    """Extract the structured payload from a FastMCP ``call_tool`` result."""
    if isinstance(result, tuple):
        blocks, structured = result
        if isinstance(structured, dict):
            return structured
    else:
        blocks = result
    blocks = blocks if isinstance(blocks, list) else [blocks]
    text = next(b.text for b in blocks if getattr(b, "type", None) == "text")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Clock-skew / out-of-order ingestion
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_out_of_order_ingestion_preserves_trend_factor(mcp_server):
    """Ingesting windows out-of-order still yields a slope from >=2 points."""
    scrambled = [
        ("2026-07-02T10:00:00Z", 100.0),  # ingested first
        ("2026-07-02T08:00:00Z", 70.0),
        ("2026-07-02T09:00:00Z", 90.0),
    ]
    for ts, hr in scrambled:
        await mcp_server.call_tool(
            "ingest_vitals",
            {
                "patient_id": "PT-HR",
                "observations": [make_fhir_obs("8867-4", hr, patient_id="PT-HR", effective=ts)],
            },
        )
    episode_id = _payload(
        await mcp_server.call_tool("discover_episode", {"patient_id": "PT-HR"})
    )["episode_id"]
    forecast = _payload(
        await mcp_server.call_tool(
            "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
        )
    )
    # Least-squares slope is computed across whatever history exists (>=2 pts);
    # the key invariant is that it is non-trivial and bounded.
    assert "heart_rate_trend" in forecast["contributing_factors"]
    assert 0.0 <= forecast["forecasted_vitals"]["heart_rate"] <= 300.0


# --------------------------------------------------------------------------- #
# Extreme boundary / rate-of-change spikes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_steep_rising_trend_clamped_to_ceiling(mcp_server):
    """A steep rising HR trend cannot extrapolate past the physiological max."""
    # 150 -> 180 -> 210 over 5-minute gaps => +360/hr; current 210 -> 570 -> 300.
    sequence = [
        ("2026-07-02T08:00:00Z", 150.0),
        ("2026-07-02T08:05:00Z", 180.0),
        ("2026-07-02T08:10:00Z", 210.0),
    ]
    for ts, hr in sequence:
        await mcp_server.call_tool(
            "ingest_vitals",
            {
                "patient_id": "PT-HI",
                "observations": [make_fhir_obs("8867-4", hr, patient_id="PT-HI", effective=ts)],
            },
        )
    episode_id = _payload(
        await mcp_server.call_tool("discover_episode", {"patient_id": "PT-HI"})
    )["episode_id"]
    forecast = _payload(
        await mcp_server.call_tool(
            "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
        )
    )
    assert forecast["forecasted_vitals"]["heart_rate"] == pytest.approx(300.0, abs=0.01)


@pytest.mark.asyncio
async def test_steep_falling_trend_clamped_to_floor(mcp_server):
    """A steep falling HR trend cannot extrapolate below the physiological floor."""
    sequence = [
        ("2026-07-02T08:00:00Z", 120.0),
        ("2026-07-02T08:05:00Z", 90.0),
        ("2026-07-02T08:10:00Z", 60.0),
    ]
    for ts, hr in sequence:
        await mcp_server.call_tool(
            "ingest_vitals",
            {
                "patient_id": "PT-LO",
                "observations": [make_fhir_obs("8867-4", hr, patient_id="PT-LO", effective=ts)],
            },
        )
    episode_id = _payload(
        await mcp_server.call_tool("discover_episode", {"patient_id": "PT-LO"})
    )["episode_id"]
    forecast = _payload(
        await mcp_server.call_tool(
            "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
        )
    )
    # Steep -720/hr slope from 60 -> clamped to the heart-rate floor (0.0).
    assert forecast["forecasted_vitals"]["heart_rate"] == pytest.approx(0.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Data staleness propagation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stale_data_flag_propagated_via_mcp(mcp_server):
    """A >300s-old window raises stale_data_warning through the MCP tool."""
    effective = _iso(datetime.now(timezone.utc) - timedelta(seconds=600))
    ingest = await mcp_server.call_tool(
        "ingest_vitals",
        {
            "patient_id": "PT-ST",
            "observations": [
                make_fhir_obs("8867-4", 72.0, patient_id="PT-ST", effective=effective),
            ],

        },
    )
    episode_id = _payload(ingest)["episode_id"]
    forecast = _payload(
        await mcp_server.call_tool(
            "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
        )
    )
    assert forecast["stale_data_warning"] is True
    assert "stale_data_warning" in forecast["contributing_factors"]


@pytest.mark.asyncio
async def test_fresh_window_has_no_stale_flag(httpx_client):
    """A window ingested moments ago does NOT raise the stale flag."""
    effective = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
    r = await httpx_client.post(
        f"{_PT}/v2/vitals/ingest",
        json={
            "patient_id": "PT-FRESH",
            "observations": [
                make_fhir_obs("8867-4", 72.0, patient_id="PT-FRESH", effective=effective),
            ],
        },
    )
    assert r.status_code == 200
    fresh_id = r.json()["episode_id"]
    r = await httpx_client.get(f"{_PT}/v2/episodes/{fresh_id}/forecast?horizon_minutes=60")
    assert r.status_code == 200
    forecast = r.json()
    assert forecast["stale_data_warning"] is False


@pytest.mark.asyncio
async def test_stale_window_flag_via_deterioration_endpoint(httpx_client):
    """Stale data surfaces the warning on the v2 deterioration endpoint too."""
    effective = _iso(datetime.now(timezone.utc) - timedelta(seconds=700))
    r = await httpx_client.post(
        f"{_PT}/v2/vitals/ingest",
        json={
            "patient_id": "PT-STALE",
            "observations": [
                make_fhir_obs("8867-4", 72.0, patient_id="PT-STALE", effective=effective),
            ],
        },
    )
    assert r.status_code == 200
    stale_id = r.json()["episode_id"]
    r = await httpx_client.get(f"{_PT}/v2/episodes/{stale_id}/deterioration")
    assert r.status_code == 200
    payload = r.json()
    assert "stale_data_warning" in payload["contributing_factors"]

"""Tests for MCP server tool execution (v2 baseline).

Exercises the FastMCP server produced by ``src.adapters.mcp.server`` via
``call_tool`` against the v2 episode-keyed tool surface (ingest_vitals ->
get_forecast / get_deterioration_index by episode_id), per docs/BASELINE.md §3.
"""

import json

import pytest

from src.adapters.mcp.server import create_mcp_server
from src.dependencies import reset_dependencies
from src.vitals_state import _vitals_store


@pytest.fixture
def mcp_server():
    reset_dependencies()
    _vitals_store.clear()
    return create_mcp_server()


def _text(result) -> dict:
    """Extract the JSON payload from a FastMCP ``call_tool`` result.

    FastMCP returns a ``(blocks, structured)`` pair (or just blocks); we prefer
    the structured mapping when present, otherwise fall back to the first
    ``text`` content block.
    """
    if isinstance(result, tuple):
        blocks, structured = result
        if isinstance(structured, dict):
            return structured
        result = blocks
    blocks = result if isinstance(result, list) else [result]
    text = next(b.text for b in blocks if getattr(b, "type", None) == "text")
    return json.loads(text)


def _obs(patient_id: str, hr: float, loinc: str = "8867-4", unit: str = "bpm",
         ts: str = "2026-07-02T08:00:00Z"):
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": "Test"}]},
        "valueQuantity": {"value": hr, "unit": unit},
        "effectiveDateTime": ts,
    }


CRITICAL = [
    ("8867-4", 140.0),  # HR critical
    ("8480-6", 80.0),   # SBP low
    ("2708-6", 88.0),   # SpO2 severe
    ("9279-1", 28.0),   # RR critical
]


@pytest.mark.asyncio
async def test_ingest_single_observation(mcp_server):
    result = await mcp_server.call_tool(
        "ingest_vitals", {"patient_id": "PT-001", "observations": [_obs("PT-001", 72.0)]}
    )
    data = _text(result)
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0
    assert data["episode_id"].startswith("E-")
    assert len(data["episode_id"]) > len("PT-001") + 2  # UUID suffix present
    assert "_meta" in data


@pytest.mark.asyncio
async def test_forecast_after_ingest(mcp_server):
    ingest = await mcp_server.call_tool(
        "ingest_vitals", {"patient_id": "PT-002", "observations": [_obs("PT-002", 72.0)]}
    )
    episode_id = _text(ingest)["episode_id"]
    result = await mcp_server.call_tool(
        "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
    )
    payload = _text(result)
    assert "forecasted_vitals" in payload
    assert "data_freshness_seconds" in payload
    assert "_meta" in payload


@pytest.mark.asyncio
async def test_deterioration_normal(mcp_server):
    ingest = await mcp_server.call_tool(
        "ingest_vitals", {"patient_id": "PT-003", "observations": [_obs("PT-003", 72.0)]}
    )
    episode_id = _text(ingest)["episode_id"]
    result = await mcp_server.call_tool(
        "get_deterioration_index", {"episode_id": episode_id}
    )
    data = _text(result)
    assert data["episode_id"].startswith("E-")
    assert data["severity"] == "NORMAL"
    assert data["ensemble_score"] == 0.0
    assert isinstance(data["contributing_factors"], list)


@pytest.mark.asyncio
async def test_deterioration_emergency(mcp_server):
    observations = [_obs("PT-004", value, loinc=loinc) for loinc, value in CRITICAL]
    ingest = await mcp_server.call_tool(
        "ingest_vitals", {"patient_id": "PT-004", "observations": observations}
    )
    episode_id = _text(ingest)["episode_id"]
    result = await mcp_server.call_tool(
        "get_deterioration_index", {"episode_id": episode_id}
    )
    data = _text(result)
    assert data["episode_id"].startswith("E-")
    assert data["severity"] == "EMERGENCY"
    assert len(data["contributing_factors"]) > 0


@pytest.mark.asyncio
async def test_discover_episode_after_ingest(mcp_server):
    ingest = await mcp_server.call_tool(
        "ingest_vitals", {"patient_id": "PT-005", "observations": [_obs("PT-005", 72.0)]}
    )
    episode_id = _text(ingest)["episode_id"]
    result = await mcp_server.call_tool("discover_episode", {"patient_id": "PT-005"})
    data = _text(result)
    assert data["episode_id"] == episode_id

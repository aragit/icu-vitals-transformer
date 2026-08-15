"""Contract tests for the MCP driving adapter surface.

Exercises the FastMCP server produced by ``src.adapters.mcp.server`` via its
public ``list_tools`` / ``call_tool`` APIs (not HTTP), asserting that every
tool:
  * is registered with the expected name + description, and
  * returns a result carrying the mandatory ``_meta`` envelope (clinical
disclaimer + data freshness).
"""

from __future__ import annotations

import json

import pytest

from src.adapters.mcp.server import create_mcp_server
from src.dependencies import reset_dependencies
from src.vitals_state import _vitals_store

pytestmark = pytest.mark.contract


def _obs(patient_id: str, hr: float, loinc: str = "8867-4") -> dict:
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc}]},
        "valueQuantity": {"value": hr, "unit": "bpm"},
        "effectiveDateTime": "2026-07-02T08:00:00Z",
    }


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


@pytest.mark.asyncio
async def test_tool_registry_exposes_phase4_surface(mcp_server):
    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "ingest_vitals",
        "get_forecast",
        "get_deterioration_index",
        "discover_episode",
        "discover_capabilities",
    }
    descriptions = {t.name: (t.description or "") for t in tools}
    assert descriptions["ingest_vitals"]
    assert descriptions["get_forecast"]
    assert descriptions["get_deterioration_index"]
    assert descriptions["discover_episode"]


@pytest.mark.asyncio
async def test_ingest_vitals_returns_meta(mcp_server):
    result = await mcp_server.call_tool(
        "ingest_vitals",
        {"patient_id": "PT-M1", "observations": [_obs("PT-M1", 72.0)]},
    )
    payload = _text(result)
    assert payload["heart_rate"] == 72.0
    assert payload["episode_id"] == "E-PT-M1"
    _meta = payload["_meta"]
    assert _meta["clinical_disclaimer"]
    assert isinstance(_meta["data_freshness_seconds"], int)


@pytest.mark.asyncio
async def test_forecast_tool_returns_meta(mcp_server):
    await mcp_server.call_tool(
        "ingest_vitals",
        {"patient_id": "PT-M2", "observations": [_obs("PT-M2", 72.0)]},
    )
    result = await mcp_server.call_tool(
        "get_forecast", {"episode_id": "E-PT-M2", "horizon_minutes": 60}
    )
    payload = _text(result)
    assert "forecasted_vitals" in payload
    _meta = payload["_meta"]
    assert _meta["clinical_disclaimer"]
    assert "data_freshness_seconds" in _meta


@pytest.mark.asyncio
async def test_deterioration_index_returns_meta(mcp_server):
    await mcp_server.call_tool(
        "ingest_vitals",
        {"patient_id": "PT-M3", "observations": [_obs("PT-M3", 72.0)]},
    )
    result = await mcp_server.call_tool(
        "get_deterioration_index", {"episode_id": "E-PT-M3"}
    )
    payload = _text(result)
    assert "ensemble_score" in payload
    _meta = payload["_meta"]
    assert _meta["clinical_disclaimer"]
    assert "data_freshness_seconds" in _meta


@pytest.mark.asyncio
async def test_discover_episode_returns_meta(mcp_server):
    await mcp_server.call_tool(
        "ingest_vitals",
        {"patient_id": "PT-M4", "observations": [_obs("PT-M4", 72.0)]},
    )
    result = await mcp_server.call_tool("discover_episode", {"patient_id": "PT-M4"})
    payload = _text(result)
    assert payload["episode_id"] == "E-PT-M4"
    _meta = payload["_meta"]
    assert _meta["clinical_disclaimer"]


@pytest.mark.asyncio
async def test_discover_capabilities_tool_exposed(mcp_server):
    """Phase B.1: discover_capabilities is registered as an MCP tool."""
    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    assert "discover_capabilities" in names


@pytest.mark.asyncio
async def test_discover_capabilities_tool_returns_caps(mcp_server):
    """Calling discover_capabilities returns the capability matrix with _meta."""
    result = await mcp_server.call_tool("discover_capabilities", {})
    payload = _text(result)
    assert len(payload["tools"]) >= 4
    assert "safety_bounds" in payload
    assert "loinc_mapping" in payload
    assert "_meta" in payload
    assert payload["_meta"]["clinical_disclaimer"]

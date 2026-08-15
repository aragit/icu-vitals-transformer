"""End-to-end workflow: ingest -> trend -> forecast -> DDS -> _meta envelope.

Drives the full pipeline through both the REST v2 transport and the FastMCP
driving adapter, asserting the SafetyShell-bounded trend extrapolation and the
mandatory ``_meta`` clinical-disclaimer / data-freshness envelope at every hop.
"""

from __future__ import annotations

import json

import pytest

from tests.e2e.factories import make_fhir_obs

pytestmark = pytest.mark.e2e

_BASE = "http://test"


def _check_meta(payload: dict) -> None:
    assert "_meta" in payload
    meta = payload["_meta"]
    assert meta["clinical_disclaimer"]
    assert isinstance(meta["data_freshness_seconds"], int)


def _mcp_payload(result) -> dict:
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


@pytest.mark.asyncio
async def test_rest_v2_full_lifecycle(httpx_client):
    """POST ingest -> forecast -> deterioration -> discovery all return _meta."""
    obs = [
        make_fhir_obs("8867-4", 72.0, patient_id="PT-E2E"),
        make_fhir_obs("8480-6", 97.0, patient_id="PT-E2E"),
        make_fhir_obs("2708-6", 98.0, patient_id="PT-E2E"),
    ]

    r = await httpx_client.post(
        f"{_BASE}/v2/vitals/ingest",
        json={"patient_id": "PT-E2E", "observations": obs},
    )
    assert r.status_code == 200
    ingest = r.json()
    _check_meta(ingest)
    assert ingest["heart_rate"] == 72.0
    episode_id = ingest["episode_id"]
    assert episode_id.startswith("E-")

    r = await httpx_client.get(f"{_BASE}/v2/episodes/{episode_id}/forecast?horizon_minutes=60")
    assert r.status_code == 200
    forecast = r.json()
    _check_meta(forecast)
    assert "forecasted_vitals" in forecast

    r = await httpx_client.get(f"{_BASE}/v2/episodes/{episode_id}/deterioration")
    assert r.status_code == 200
    assessment = r.json()
    _check_meta(assessment)
    assert "ensemble_score" in assessment
    assert assessment["episode_id"] == episode_id

    r = await httpx_client.get(f"{_BASE}/v2/episodes/{episode_id}/discovery")
    assert r.status_code == 200
    discovery = r.json()
    _check_meta(discovery)
    assert "heart_rate" in discovery["channels"]


@pytest.mark.asyncio
async def test_mcp_full_lifecycle(mcp_server):
    """FastMCP tool chain: ingest -> forecast -> deterioration -> _meta."""
    obs = make_fhir_obs("8867-4", 72.0, patient_id="PT-E2E")

    ingest = await mcp_server.call_tool(
        "ingest_vitals",
        {"patient_id": "PT-E2E", "observations": [obs]},
    )
    ingest = _mcp_payload(ingest)
    _check_meta(ingest)
    assert ingest["heart_rate"] == 72.0
    episode_id = ingest["episode_id"]

    forecast = await mcp_server.call_tool(
        "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
    )
    forecast = _mcp_payload(forecast)
    _check_meta(forecast)
    assert "forecasted_vitals" in forecast

    assessment = await mcp_server.call_tool(
        "get_deterioration_index", {"episode_id": episode_id}
    )
    assessment = _mcp_payload(assessment)
    _check_meta(assessment)
    assert "ensemble_score" in assessment

    discovery = await mcp_server.call_tool("discover_episode", {"patient_id": "PT-E2E"})
    discovery = _mcp_payload(discovery)
    _check_meta(discovery)
    assert discovery["episode_id"] == episode_id


@pytest.mark.asyncio
async def test_mcp_trend_extrapolation_end_to_end(mcp_server, _trend_history):
    """A rising HR trend extrapolates linearly through the MCP forecast tool."""
    for hr, ts in _trend_history:
        await mcp_server.call_tool(
            "ingest_vitals",
            {
                "patient_id": "PT-HR",
                "observations": [make_fhir_obs("8867-4", hr, patient_id="PT-HR", effective=ts)],
            },
        )
    episode_id = (await mcp_server.call_tool("discover_episode", {"patient_id": "PT-HR"}))
    episode_id = _mcp_payload(episode_id)["episode_id"]
    forecast = await mcp_server.call_tool(
        "get_forecast", {"episode_id": episode_id, "horizon_minutes": 60}
    )
    forecast = _mcp_payload(forecast)
    hr = forecast["forecasted_vitals"]["heart_rate"]
    # 80 -> 90 -> 100 one hour apart => +10/hr => 100 + 10 = 110 @ +60m.
    assert hr == pytest.approx(110.0, abs=0.5)
    assert "heart_rate_trend" in forecast["contributing_factors"]
    _check_meta(forecast)


@pytest.mark.asyncio
async def test_v2_ingest_resolves_episode_and_window(httpx_client):
    """v2 ingest resolves an episode and windows values to the parsed input."""
    obs = [
        make_fhir_obs("8867-4", 76.0, patient_id="PT-PARITY"),
        make_fhir_obs("8480-6", 118.0, patient_id="PT-PARITY"),
    ]
    r = await httpx_client.post(
        f"{_BASE}/v2/vitals/ingest",
        json={"patient_id": "PT-PARITY", "observations": obs},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["episode_id"].startswith("E-")
    assert body["patient_id"] == "PT-PARITY"
    assert body["heart_rate"] == 76.0
    assert body["systolic_bp"] == 118.0
    assert "clinical_disclaimer" in body["_meta"]

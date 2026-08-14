"""Contract tests: MCP tool definitions & JSON-RPC execution (baseline).

Validate the public MCP tool surface declared in
``src/mcp_server/server.py`` against the legacy tool handlers, per
docs/BASELINE.md §3. Exercises the registered handlers
(``list_tools`` / ``call_tool``) directly — these are the JSON-RPC
invocation entrypoints exposed by the MCP Server.
"""

import json

import pytest

from src.mcp_server.server import (
    _handle_deterioration,
    _handle_forecast,
    _handle_ingest,
    _vitals_store,
    call_tool,
    list_tools,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def clear_store():
    _vitals_store.clear()
    yield
    _vitals_store.clear()


def _fhir_obs(loinc="8867-4", value=72.0, patient_id="PT-001", unit="bpm"):
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc}]},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": "2026-07-02T08:00:00Z",
    }


class TestToolDefinitions:
    async def test_three_tools_exposed(self):
        tools = await list_tools()
        names = sorted(t.name for t in tools)
        assert names == ["get_deterioration_index", "get_forecast", "ingest_vitals"]

    async def test_ingest_tool_schema(self):
        tools = {t.name: t for t in await list_tools()}
        ingest = tools["ingest_vitals"]
        assert "Ingest FHIR R4 Observations" in ingest.description
        schema = ingest.inputSchema
        assert schema["type"] == "object"
        assert schema["required"] == ["patient_id", "observations"]
        assert "patient_id" in schema["properties"]
        assert "observations" in schema["properties"]

    async def test_forecast_tool_schema(self):
        tools = {t.name: t for t in await list_tools()}
        schema = tools["get_forecast"].inputSchema
        assert schema["required"] == ["patient_id"]
        assert "horizon_minutes" in schema["properties"]
        assert schema["properties"]["horizon_minutes"]["default"] == 60

    async def test_deterioration_tool_schema(self):
        tools = {t.name: t for t in await list_tools()}
        schema = tools["get_deterioration_index"].inputSchema
        assert schema["required"] == ["patient_id"]


class TestToolExecution:
    async def test_ingest_handler_returns_windowed_vitals(self):
        result = await _handle_ingest({"patient_id": "PT-001", "observations": [_fhir_obs()]})
        data = json.loads(result[0].text)
        assert data["patient_id"] == "PT-001"
        assert data["heart_rate"] == 72.0

    async def test_ingest_handler_error_on_invalid(self):
        obs = {"resourceType": "Patient"}
        result = await _handle_ingest({"patient_id": "PT-001", "observations": [obs]})
        assert "error" in json.loads(result[0].text)

    async def test_ingest_handler_error_on_empty(self):
        result = await _handle_ingest({"patient_id": "PT-001", "observations": []})
        assert "error" in json.loads(result[0].text)

    async def test_forecast_handler_after_ingest(self):
        await _handle_ingest({"patient_id": "PT-001", "observations": [_fhir_obs()]})
        result = await _handle_forecast({"patient_id": "PT-001", "horizon_minutes": 60})
        data = json.loads(result[0].text)
        assert data["patient_id"] == "PT-001"
        assert data["horizon_minutes"] == 60
        assert data["severity"] == "NORMAL"
        assert "forecasted_vitals" in data

    async def test_forecast_handler_unknown_patient(self):
        result = await _handle_forecast({"patient_id": "PT-999", "horizon_minutes": 60})
        assert "error" in json.loads(result[0].text)

    async def test_forecast_handler_invalid_horizon(self):
        await _handle_ingest({"patient_id": "PT-001", "observations": [_fhir_obs()]})
        result = await _handle_forecast({"patient_id": "PT-001", "horizon_minutes": 30})
        assert "error" in json.loads(result[0].text)

    async def test_deterioration_handler_normal(self):
        await _handle_ingest({"patient_id": "PT-001", "observations": [_fhir_obs()]})
        result = await _handle_deterioration({"patient_id": "PT-001"})
        data = json.loads(result[0].text)
        assert data["severity"] == "NORMAL"
        assert data["ensemble_score"] == 0.0
        assert data["contributing_factors"] == []

    async def test_deterioration_handler_unknown_patient(self):
        result = await _handle_deterioration({"patient_id": "PT-999"})
        assert "error" in json.loads(result[0].text)


class TestRouterDispatch:
    async def test_call_tool_routes_to_handlers(self):
        # JSON-RPC-style dispatch via the registered call_tool entrypoint.
        await call_tool("ingest_vitals", {"patient_id": "PT-001", "observations": [_fhir_obs()]})
        result = await call_tool("get_deterioration_index", {"patient_id": "PT-001"})
        data = json.loads(result[0].text)
        assert data["patient_id"] == "PT-001"

    async def test_call_tool_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("does_not_exist", {})

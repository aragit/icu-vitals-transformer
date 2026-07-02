"""MCP server exposing ICU vitals forecasting tools.

Uses stdio transport for local agent orchestrators.
"""

import json
from datetime import datetime, timezone

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.config import settings
from src.observability.metrics import MCP_TOOL_CALLS
from src.ingestion.fhir_parser import parse_batch
from src.ingestion.windowing import window_vitals
from src.forecasting.ensemble import ensemble_forecast, ensemble_deterioration_index
from src.models.mcp import IngestVitalsInput, GetForecastInput, GetDeteriorationInput


# In-memory store for demo (caller manages persistence)
_vitals_store: dict[str, list[dict]] = {}


app = Server(settings.mcp_server_name)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Expose available tools."""
    return [
        Tool(
            name="ingest_vitals",
            description="Ingest FHIR R4 Observations and return windowed vital signs. Accepts raw FHIR JSON dicts.",
            inputSchema=IngestVitalsInput.model_json_schema(),
        ),
        Tool(
            name="get_forecast",
            description="Generate multi-horizon deterioration forecast (1h, 4h, 12h) for a patient.",
            inputSchema=GetForecastInput.model_json_schema(),
        ),
        Tool(
            name="get_deterioration_index",
            description="Compute ensemble deterioration index and severity classification.",
            inputSchema=GetDeteriorationInput.model_json_schema(),
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls."""
    MCP_TOOL_CALLS.inc()
    if name == "ingest_vitals":
        return await _handle_ingest(arguments)
    elif name == "get_forecast":
        return await _handle_forecast(arguments)
    elif name == "get_deterioration_index":
        return await _handle_deterioration(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def _handle_ingest(arguments: dict) -> list[TextContent]:
    """Handle ingest_vitals tool."""
    patient_id = arguments.get("patient_id", "unknown")
    observations = arguments.get("observations", [])

    parsed = parse_batch(observations)
    if not parsed:
        return [TextContent(type="text", text=json.dumps({"error": "No valid observations parsed"}))]

    # Store for later retrieval (in-memory only)
    if patient_id not in _vitals_store:
        _vitals_store[patient_id] = []
    _vitals_store[patient_id].extend(parsed)

    window = window_vitals(parsed, patient_id)
    if not window:
        return [TextContent(type="text", text=json.dumps({"error": "Could not window vitals"}))]

    return [TextContent(type="text", text=window.model_dump_json())]


async def _handle_forecast(arguments: dict) -> list[TextContent]:
    """Handle get_forecast tool."""
    patient_id = arguments.get("patient_id", "unknown")
    horizon = arguments.get("horizon_minutes", 60)

    records = _vitals_store.get(patient_id, [])
    if not records:
        return [TextContent(type="text", text=json.dumps({"error": f"No vitals stored for {patient_id}"}))]

    window = window_vitals(records, patient_id)
    if not window:
        return [TextContent(type="text", text=json.dumps({"error": "Could not window vitals"}))]

    forecasts = ensemble_forecast(window)
    target = [f for f in forecasts if f.horizon_minutes == horizon]
    if not target:
        return [TextContent(type="text", text=json.dumps({"error": f"Horizon {horizon} not available"}))]

    return [TextContent(type="text", text=target[0].model_dump_json())]


async def _handle_deterioration(arguments: dict) -> list[TextContent]:
    """Handle get_deterioration_index tool."""
    patient_id = arguments.get("patient_id", "unknown")

    records = _vitals_store.get(patient_id, [])
    if not records:
        return [TextContent(type="text", text=json.dumps({"error": f"No vitals stored for {patient_id}"}))]

    window = window_vitals(records, patient_id)
    if not window:
        return [TextContent(type="text", text=json.dumps({"error": "Could not window vitals"}))]

    forecasts = ensemble_forecast(window)
    assessment = ensemble_deterioration_index(forecasts)

    return [TextContent(type="text", text=assessment.model_dump_json())]

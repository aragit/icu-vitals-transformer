"""Capability negotiation & discovery (MCP driving adapter).

Exposes a pure-data ``discover_capabilities()`` that returns the canonical
capability matrix consumed by the ``GET /discover`` REST surface. Keeping this
logic in the adapter (not the hex core) preserves Core Isolation.
"""

from __future__ import annotations

from typing import Any

from src.config import settings
from src.core.forecasting.forecaster import BOUNDS, NUMERIC_FIELDS
from src.core.ingestion.fhir_parser import LOINC_CODES

_TOOL_DESCRIPTIONS = {
    "ingest_vitals": "Ingest FHIR observations; auto-resolve or create the active episode.",
    "get_forecast": "SafetyShell-bounded trend forecast for an episode.",
    "get_deterioration_index": "DDS assessment + severity tier for an episode.",
    "discover_episode": "Active episode for a patient, or episodes array when multiple active.",
    "discover_capabilities": "Return the server capability matrix (tools, safety bounds).",
}


def discover_capabilities() -> dict[str, Any]:
    """Return the server capability matrix as a JSON-serializable dict."""
    tools = [
        {
            "name": name,
            "description": desc,
            "inputSchema": _schema_for(name),
        }
        for name, desc in _TOOL_DESCRIPTIONS.items()
    ]
    return {
        "server": {
            "name": settings.mcp_server_name,
            "version": settings.app_version,
        },
        "protocols": ["mcp", "rest"],
        "transports": {
            "mcp": "streamable-http",
            "rest_versions": ["v1", "v2"],
        },
        "tools": tools,
        "safety_bounds": {field: list(bounds) for field, bounds in BOUNDS.items()},
        "loinc_mapping": dict(LOINC_CODES),
        "numeric_fields": list(NUMERIC_FIELDS),
    }


def _schema_for(tool_name: str) -> dict[str, Any]:
    """Stub schemas mirroring the registered MCP tools."""
    if tool_name == "ingest_vitals":
        return {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "observations": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["patient_id", "observations"],
        }
    if tool_name == "get_forecast":
        return {
            "type": "object",
            "properties": {
                "episode_id": {"type": "string"},
                "horizon_minutes": {"type": "integer", "default": 60},
            },
            "required": ["episode_id"],
        }
    if tool_name == "get_deterioration_index":
        return {
            "type": "object",
            "properties": {"episode_id": {"type": "string"}},
            "required": ["episode_id"],
        }
    if tool_name == "discover_episode":
        return {
            "type": "object",
            "properties": {"patient_id": {"type": "string"}},
            "required": ["patient_id"],
        }
    if tool_name == "discover_capabilities":
        return {"type": "object", "properties": {}, "required": []}
    return {"type": "object"}

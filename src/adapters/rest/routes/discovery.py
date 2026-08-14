"""Capability negotiation endpoint (REST driving adapter).

``GET /discover`` returns the server capability matrix (protocol versions,
active tools, resource URIs, safety bounds) so agents can negotiate supported
operations before invoking the v2/MCP surfaces.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.adapters.mcp.discovery import discover_capabilities

router = APIRouter(tags=["discovery"])


@router.get("/discover")
async def discover() -> dict[str, Any]:
    """Return the server capability matrix."""
    capabilities = discover_capabilities()
    capabilities["_meta"] = {
        "clinical_disclaimer": (
            "This output is informational only. Not FDA/CE marked. "
            "Must be reviewed by a qualified clinician before any action."
        )
    }
    return capabilities

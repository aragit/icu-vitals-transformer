"""Capability negotiation endpoint (REST driving adapter).

``GET /discover`` returns the server capability matrix (protocol versions,
active tools, safety bounds) so agents can negotiate supported operations
before invoking the v2/MCP surfaces. The static clinical safety disclaimer is
surfaced here as a top-level ``disclaimer`` field (and in the MCP server
``instructions``); it is intentionally not embedded in every response ``_meta``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.adapters.mcp.discovery import discover_capabilities
from src.adapters.rest.metadata import build_meta
from src.core.domain.disclaimer import CLINICAL_SAFETY_DISCLAIMER

router = APIRouter(tags=["discovery"])


@router.get("/discover")
async def discover() -> dict[str, Any]:
    """Return the server capability matrix."""
    capabilities = discover_capabilities()
    capabilities["disclaimer"] = CLINICAL_SAFETY_DISCLAIMER
    capabilities["_meta"] = build_meta(0)
    return capabilities

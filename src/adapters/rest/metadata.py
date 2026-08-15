"""Response metadata envelope helper (REST driving adapter).

Every v2 response carries a ``_meta`` block with the staleness (freshness) of
the underlying vital data, so downstream clients and clinical consumers can
gauge data provenance at a glance. The static clinical safety disclaimer is
surfaced at the server-capability level (``GET /discover`` and the MCP server
``instructions``), not repeated per response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def freshness_seconds(window_end: datetime) -> int:
    """Age of the latest observation window in whole seconds.

    Handles the legacy convention of naive UTC timestamps by assuming UTC.
    """
    end = window_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - end
    return max(0, int(delta.total_seconds()))


def build_meta(data_freshness_seconds: int) -> dict[str, Any]:
    """Construct the standard ``_meta`` envelope for v2 responses."""
    return {
        "data_freshness_seconds": data_freshness_seconds,
    }

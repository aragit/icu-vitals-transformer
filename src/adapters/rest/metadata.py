"""Response metadata envelope helper (REST driving adapter).

Every v2 response carries a ``_meta`` block with the clinical safety
disclaimer and the staleness (freshness) of the underlying vital data, so
downstream clients and clinical consumers can see at a glance both the data
provenance and the advisory nature of the output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.domain.disclaimer import CLINICAL_SAFETY_DISCLAIMER


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
        "clinical_disclaimer": CLINICAL_SAFETY_DISCLAIMER,
        "data_freshness_seconds": data_freshness_seconds,
    }

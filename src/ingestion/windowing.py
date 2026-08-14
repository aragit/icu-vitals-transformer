"""Legacy windowing shim — delegates to the Core temporal engine.

Phase 1 strangler-fig: the canonical engine lives in
``src/core/windowing/engine.py``. The Core engine anchors windows on the
most-recent observation (Phase 1 clean behavior). To preserve the Phase 0
baseline contract pinned by the test suite (window anchored on the OLDEST
record, lexicographic timestamp sort), this shim invokes the core with
``anchor="oldest"`` and converts the result back to the legacy
``src.models.vitals.VitalSignsWindow`` shape.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.windowing.engine import window_vitals as _core_window_vitals
from src.models.vitals import VitalSignsWindow

__all__ = ["window_vitals"]


def window_vitals(
    parsed_records: list[dict[str, Any]],
    patient_id: str,
    window_minutes: int = 5,
) -> Optional[VitalSignsWindow]:
    core_window = _core_window_vitals(
        parsed_records,
        patient_id,
        window_minutes=window_minutes,
        anchor="oldest",
    )
    if core_window is None:
        return None
    return VitalSignsWindow(**core_window.model_dump())

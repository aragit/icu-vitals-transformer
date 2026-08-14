"""Legacy governmentance shim — delegates DDS scoring to the Core.

Phase 1 strangler-fig: the canonical scoring lives in
``src/core/governance/deterioration.py`` as ``compute_dds`` (Deterministic
Deterioration Score). This shim preserves the legacy public name
``compute_deterioration_index`` and converts the legacy
``VitalSignsWindow`` model into the Core domain model before delegating.
"""

from __future__ import annotations

from src.core.domain.vitals import VitalSignsWindow as _CoreWindow
from src.core.governance.deterioration import compute_dds
from src.models.vitals import VitalSignsWindow

__all__ = ["compute_deterioration_index"]


def compute_deterioration_index(
    vitals: VitalSignsWindow,
    trend: str = "stable",
) -> tuple[float, list[str]]:
    core_vitals = _CoreWindow(**vitals.model_dump())
    return compute_dds(core_vitals, trend)

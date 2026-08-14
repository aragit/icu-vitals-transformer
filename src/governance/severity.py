"""Legacy severity shim — delegates to the Core governance mapper.

Phase 1 strangler-fig: canonical risk-tier mapping lives in
``src/core/governance/severity.py``.
"""

from __future__ import annotations

from src.core.governance.severity import severity_from_score

__all__ = ["severity_from_score"]

"""In-memory vital-record store (default in-process backend).

Holds the module-global ``_vitals_store`` dict of raw FHIR records consumed by
the default ``InMemoryVitalsRepository``. Tests reset it directly
(``from src.vitals_state import _vitals_store``) between cases.

⚠️ SINGLE-INSTANCE ONLY. For dev/test or single-replica deployments. Production
multi-replica deployments MUST use ``src.dependencies.get_vitals_repo()``
(which selects a network-capable adapter) — these in-process structures do
NOT replicate across replicas and will lose state on restart / scale-out.
"""

from __future__ import annotations

from typing import Any

_vitals_store: dict[str, list[dict[str, Any]]] = {}

__all__ = ["_vitals_store"]

"""Legacy in-memory vital-record store (shared state shim).

Historically the Phase 0 baseline lived in ``src/mcp_server/server.py`` as the
module-global ``_vitals_store`` dict of raw FHIR records, and baseline
fixtures reset it via ``from src.mcp_server.server import _vitals_store``.

The v1 REST routes (``src/api/routes/vitals.py``) and the legacy MCP surface
have been retired; that dict now lives dependency-free in this module, and all
tests import it directly (``from src.vitals_state import _vitals_store``).

⚠️ SINGLE-INSTANCE ONLY / DEPRECATED: prefer ``src.dependencies.get_vitals_repo()``
for any new code. This shim only exists to keep Phase 0 reset fixtures working
during the strangler migration.
"""

from __future__ import annotations

from typing import Any

_vitals_store: dict[str, list[dict[str, Any]]] = {}

__all__ = ["_vitals_store"]

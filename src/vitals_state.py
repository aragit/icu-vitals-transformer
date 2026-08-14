"""Legacy in-memory vital-record store (shared state shim).

Historically the Phase 0 baseline lived in ``src/mcp_server/server.py`` as the
module-global ``_vitals_store`` dict of raw FHIR records, and every baseline
test fixture reset it via ``from src.mcp_server.server import _vitals_store``.

To break the REST v1 routes (`src/api/routes/vitals.py`) and the MCP stdio entry
point free of a hard import on the legacy MCP ``Server`` module — which has a
fragile, SDK-version-dependent decorator surface — that dict now lives in this
dependency-free module. ``src.mcp_server.server`` re-exports it so all existing
test imports (``from src.mcp_server.server import _vitals_store``) keep working
unchanged.

⚚️ SINGLE-INSTANCE ONLY / DEPRECATED: prefer ``src.dependencies.get_vitals_repo()``
for any new code. This shim only exists to keep the Phase 0 baseline suite green
while the strangler migration proceeds.
"""

from __future__ import annotations

from typing import Any

_vitals_store: dict[str, list[dict[str, Any]]] = {}

__all__ = ["_vitals_store"]

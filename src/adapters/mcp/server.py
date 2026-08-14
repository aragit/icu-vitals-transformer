"""FastMCP server factory (MCP driving adapter).

Creates an ``mcp.server.fastmcp.FastMCP`` instance bound to the
``icu-vitals-transformer`` logical tool server and registers the Phase 4 tools
defined in ``src.adapters.mcp.tools``.

Transport is configurable via the ``MCP_TRANSPORT`` environment variable
(``http`` -> Streamable HTTP, the production default; ``stdio`` for local dev).
The factory exposes both ``create_mcp_server`` (tool registration) and
``run_mcp_server`` (transport selection) so the entry point can switch
transports without touching the hex core.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from src.adapters.mcp.tools import register_tools
from src.config import settings

# Map the friendly env value to FastMCP's accepted transport literal.
_TRANSPORT_ALIAS = {
    "http": "streamable-http",
    "stdio": "stdio",
    "sse": "sse",
    "streamable-http": "streamable-http",
}


def _resolve_transport() -> str:
    """Resolve the MCP transport from ENV, falling back to settings."""
    env_value = os.environ.get(settings.mcp_transport_env, "").strip().lower()
    if env_value:
        return _TRANSPORT_ALIAS.get(env_value, env_value)
    configured = (settings.mcp_transport or "").strip().lower()
    return _TRANSPORT_ALIAS.get(configured, configured)


def create_mcp_server(name: str | None = None) -> FastMCP:
    """Build the MCP server with the vitals/forecast tool surface."""
    server = FastMCP(name or settings.mcp_server_name)
    register_tools(server)
    return server


def run_mcp_server(server: FastMCP, transport: str | None = None) -> None:
    """Run the MCP server on the resolved (or overridden) transport.

    ``http`` maps to FastMCP's Streamable HTTP (stateless, per-request). Passing
    ``transport`` explicitly overrides the environment/setting resolution.
    """
    resolved = transport or _resolve_transport()
    server.run(transport=resolved)  # type: ignore[arg-type]


__all__ = ["create_mcp_server", "run_mcp_server"]

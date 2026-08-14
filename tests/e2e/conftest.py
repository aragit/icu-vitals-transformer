"""Shared fixtures for Phase 5 E2E tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.adapters.mcp.server import create_mcp_server
from src.dependencies import reset_dependencies
from src.main import app
from src.mcp_server.server import _vitals_store
from tests.e2e.factories import make_fhir_obs  # noqa: F401  (re-exported)


@pytest.fixture(autouse=True)
def _reset_state():
    """Isolate each E2E test: fresh DI singletons + legacy raw store."""
    reset_dependencies()
    _vitals_store.clear()
    yield


@pytest.fixture
async def httpx_client():
    """A shared async httpx client bound to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mcp_server():
    """A freshly-registered FastMCP server over the hex core."""
    return create_mcp_server()


@pytest.fixture
def _trend_history():
    """HR 80->90->100 one hour apart (=> +10/hr least-squares slope)."""
    return [
        (80.0, "2026-07-02T08:00:00Z"),
        (90.0, "2026-07-02T09:00:00Z"),
        (100.0, "2026-07-02T10:00:00Z"),
    ]

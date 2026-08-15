"""Contract tests: MCP tool registry & schema definitions (v2 baseline).

Validates the FastMCP tool surface produced by ``src.adapters.mcp.server`` via
``create_mcp_server()``: the Phase 4 tool set is registered with the expected
names, descriptions, and JSON-RPC input schemas. Tool execution is covered by
tests/contract/mcp/test_mcp_adapter.py and tests/test_mcp_server.py.
See docs/BASELINE.md §3.
"""

import pytest

from src.adapters.mcp.server import create_mcp_server
from src.dependencies import reset_dependencies
from src.vitals_state import _vitals_store

pytestmark = pytest.mark.contract


@pytest.fixture
def mcp_server():
    reset_dependencies()
    _vitals_store.clear()
    return create_mcp_server()


class TestToolDefinitions:
    async def test_phase4_tools_registered(self, mcp_server):
        tools = await mcp_server.list_tools()
        names = {t.name for t in tools}
        assert names == {
            "ingest_vitals",
            "get_forecast",
            "get_deterioration_index",
            "discover_episode",
            "discover_capabilities",
        }

    async def test_tools_have_descriptions(self, mcp_server):
        tools = await mcp_server.list_tools()
        for t in tools:
            assert t.description

    async def test_ingest_tool_schema(self, mcp_server):
        tools = {t.name: t for t in await mcp_server.list_tools()}
        schema = tools["ingest_vitals"].inputSchema
        assert schema["type"] == "object"
        assert "patient_id" in schema["required"]
        assert "observations" in schema["required"]
        assert "patient_id" in schema["properties"]

    async def test_forecast_tool_schema(self, mcp_server):
        tools = {t.name: t for t in await mcp_server.list_tools()}
        schema = tools["get_forecast"].inputSchema
        assert schema["type"] == "object"
        assert "episode_id" in schema["required"]
        assert "horizon_minutes" not in schema["required"]
        assert "horizon_minutes" in schema["properties"]
        assert schema["properties"]["horizon_minutes"]["default"] == 60

    async def test_deterioration_tool_schema(self, mcp_server):
        tools = {t.name: t for t in await mcp_server.list_tools()}
        schema = tools["get_deterioration_index"].inputSchema
        assert "episode_id" in schema["required"]
        assert "episode_id" in schema["properties"]

    async def test_discover_episode_tool_schema(self, mcp_server):
        tools = {t.name: t for t in await mcp_server.list_tools()}
        schema = tools["discover_episode"].inputSchema
        assert "patient_id" in schema["properties"]

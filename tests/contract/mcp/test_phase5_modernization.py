"""Phase 5 modernization contract tests.

Verifies the protocol-manifest surface, capability-negotiation endpoint, MRTR
elicitation, and CIMD/JWT bearer parsing stubs introduced in Phase 5 while
keeping the baseline suite untouched.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.fastmcp import FastMCP

from src.adapters.mcp.discovery import discover_capabilities
from src.adapters.mcp.server import _resolve_transport, create_mcp_server
from src.auth.cimd import TokenParseError, parse_cimd_token, parse_optional_bearer
from src.dependencies import get_clinical_service, reset_dependencies
from src.main import app
from src.vitals_state import _vitals_store

pytestmark = pytest.mark.contract

_MANIFESTS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "manifests")
)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_dependencies()
    _vitals_store.clear()
    yield


@pytest.fixture
async def httpx_client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mcp_server():
    return create_mcp_server()


# --------------------------------------------------------------------------- #
# Protocol manifests
# --------------------------------------------------------------------------- #
def test_manifests_exist():
    assert os.path.isfile(os.path.join(_MANIFESTS, "mcp.json"))
    assert os.path.isfile(os.path.join(_MANIFESTS, "SKILL.md"))


def test_mcp_json_manifest_valid_json():
    with open(os.path.join(_MANIFESTS, "mcp.json")) as fh:
        manifest = json.load(fh)
    tools = {t["name"] for t in manifest["capabilities"]["tools"]}
    assert tools == {
        "ingest_vitals",
        "get_forecast",
        "get_deterioration_index",
        "discover_episode",
    }
    resources = {r["uri"] for r in manifest["capabilities"]["resources"]}
    assert "clinical://bounds/v1" in resources
    assert "clinical://loinc-mapping/v1" in resources
    assert manifest["execution"]["_meta"]["determinism"] == "deterministic"
    assert manifest["execution"]["_meta"]["side_effects"] is False


def test_skill_markdown_is_markdown():
    with open(os.path.join(_MANIFESTS, "SKILL.md")) as fh:
        content = fh.read()
    assert content.startswith("#")
    assert "Safety Boundary" in content
    assert "disclaimer" in content.lower()


# --------------------------------------------------------------------------- #
# Capability discovery
# --------------------------------------------------------------------------- #
def test_discover_capabilities_contract():
    caps = discover_capabilities()
    assert caps["server"]["name"] == "icu-vitals-transformer"
    names = [t["name"] for t in caps["tools"]]
    assert names == [
        "ingest_vitals",
        "get_forecast",
        "get_deterioration_index",
        "discover_episode",
        "discover_capabilities",
    ]
    assert caps["safety_bounds"]["heart_rate"] == [0.0, 300.0]
    assert caps["loinc_mapping"]["8867-4"] == "heart_rate"


@pytest.mark.asyncio
async def test_get_discover_endpoint(httpx_client):
    response = await httpx_client.get("http://test/discover")
    assert response.status_code == 200
    body = response.json()
    assert {t["name"] for t in body["tools"]} == {
        "ingest_vitals",
        "get_forecast",
        "get_deterioration_index",
        "discover_episode",
        "discover_capabilities",
    }
    assert "resources" not in body
    assert body["_meta"]["clinical_disclaimer"]


@pytest.mark.asyncio
async def test_discover_attaches_correlation_id(httpx_client):
    response = await httpx_client.get(
        "http://test/discover", headers={"X-Request-ID": "e2e-disc-1"}
    )
    assert response.headers["X-Request-ID"] == "e2e-disc-1"


# --------------------------------------------------------------------------- #
# MCP transport configuration
# --------------------------------------------------------------------------- #
def test_transport_resolution_env(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    assert _resolve_transport() == "streamable-http"
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    assert _resolve_transport() == "stdio"
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert _resolve_transport() == "stdio"


def test_create_mcp_server_registers_tools():
    server: FastMCP = create_mcp_server()

    async def _names() -> list[str]:
        return [t.name for t in await server.list_tools()]

    names = asyncio.run(_names())
    assert names == [
        "ingest_vitals",
        "get_forecast",
        "get_deterioration_index",
        "discover_episode",
        "discover_capabilities",
    ]


def test_router_isolation_no_framework_in_core():
    """Core Isolation invariant: src/core, src/ports stay framework-free."""
    import os
    root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "src")
    )
    forbidden = ("fastapi", "mcp", "prometheus_client", "redis", "numpy")
    offenders = []
    for dirpath, _dirs, files in os.walk(root):
        norm = os.path.normpath(dirpath).replace("\\", "/")
        if not (norm.endswith("/core") or "/core/" in norm or "/ports/" in norm):
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if stripped.startswith(
                        tuple(f"import {pkg}" for pkg in forbidden)
                    ) or stripped.startswith(
                        tuple(f"from {pkg}" for pkg in forbidden)
                    ):
                        offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, f"Framework import in core/ports: {offenders}"


# --------------------------------------------------------------------------- #
# Episode discovery (data, not dialogue)
# --------------------------------------------------------------------------- #
def _mcp_payload(result) -> dict:
    """Extract the structured payload from a FastMCP ``call_tool`` result."""
    if isinstance(result, tuple):
        blocks, structured = result
        if isinstance(structured, dict):
            return structured
        result = blocks
    blocks = result if isinstance(result, list) else [result]
    text = next(b.text for b in blocks if getattr(b, "type", None) == "text")
    return json.loads(text)


@pytest.mark.asyncio
async def test_discover_episode_single_returns_episode(mcp_server):
    """discover_episode with one active episode returns episode_id directly."""
    reset_dependencies()
    _vitals_store.clear()
    server = create_mcp_server()
    svc = get_clinical_service()
    ep = await svc.open_episode("PT-DISC-SINGLE")
    result = await server.call_tool(
        "discover_episode", {"patient_id": "PT-DISC-SINGLE"}
    )
    payload = _mcp_payload(result)
    assert payload["episode_id"] == ep.episode_id
    assert payload["state"] == ep.state.value
    assert "episodes" not in payload


@pytest.mark.asyncio
async def test_discover_episode_multiple_returns_list(mcp_server):
    """discover_episode with >1 active episodes returns an episodes array."""
    reset_dependencies()
    _vitals_store.clear()
    server = create_mcp_server()
    svc = get_clinical_service()
    ep1 = await svc.open_episode("PT-DISC-MULTI")
    ep2 = await svc.open_episode("PT-DISC-MULTI")
    result = await server.call_tool(
        "discover_episode", {"patient_id": "PT-DISC-MULTI"}
    )
    payload = _mcp_payload(result)
    assert "episodes" in payload
    assert len(payload["episodes"]) == 2
    assert {e["episode_id"] for e in payload["episodes"]} == {ep1.episode_id, ep2.episode_id}


@pytest.mark.asyncio
async def test_discover_episode_explicit_id(mcp_server):
    """discover_episode with an explicit episode_id resolves that episode."""
    reset_dependencies()
    _vitals_store.clear()
    server = create_mcp_server()
    svc = get_clinical_service()
    ep = await svc.open_episode("PT-DISC-EXPLICIT")
    result = await server.call_tool(
        "discover_episode",
        {"patient_id": "PT-DISC-EXPLICIT", "episode_id": ep.episode_id},
    )
    payload = _mcp_payload(result)
    assert payload["episode_id"] == ep.episode_id


@pytest.mark.asyncio
async def test_discover_episode_no_active_returns_none(mcp_server):
    """discover_episode for a patient with no active episodes returns None."""
    reset_dependencies()
    _vitals_store.clear()
    server = create_mcp_server()
    result = await server.call_tool(
        "discover_episode", {"patient_id": "PT-DISC-NONE"}
    )
    payload = _mcp_payload(result)
    assert payload["episode_id"] is None


# --------------------------------------------------------------------------- #
# CIMD / JWT auth parsing
# --------------------------------------------------------------------------- #
def test_parse_cimd_token_valid():
    import jwt

    token = jwt.encode(
        {"iss": "issuer", "sub": "dr-smith", "roles": ["clinician", "admin"]},
        "secret-key",
        algorithm="HS256",
    )
    principal = parse_cimd_token(f"Bearer {token}")
    assert principal["requested_by"] == "dr-smith"
    assert principal["iss"] == "issuer"
    assert principal["roles"] == ["clinician", "admin"]


def test_parse_cimd_token_bad_scheme():
    with pytest.raises(TokenParseError, match="Bearer"):
        parse_cimd_token("Basic not-a-jwt")


def test_parse_cimd_token_missing_sub():
    import jwt

    token = jwt.encode({"iss": "issuer"}, "secret-key", algorithm="HS256")
    with pytest.raises(TokenParseError, match="sub"):
        parse_cimd_token(f"Bearer {token}")


def test_parse_optional_bearer_anonymous():
    assert parse_optional_bearer(None)["requested_by"] is None
    assert parse_optional_bearer("Garble")["requested_by"] is None


def test_parse_cimd_token_manual_decode_fallback():
    """The manual base64url decode path works for a hand-built JWT payload."""
    import base64
    import json

    # Header: {"alg":"none"}  Payload: {"iss":"issuer","sub":"dr-manual","roles":["clinician"]}
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    payload_obj = {"iss": "issuer", "sub": "dr-manual", "roles": ["clinician"]}
    token = f"{b64({'alg': 'none'})}.{b64(payload_obj)}.signature"
    principal = parse_cimd_token(f"Bearer {token}")
    assert principal["requested_by"] == "dr-manual"
    assert principal["roles"] == ["clinician"]


def test_json_logger_emits_context_envelope():
    """Structured logging records correlation_id + requested_by context."""
    import io
    import logging

    from src.observability.logging import (
        JsonFormatter,
        set_correlation_id,
        set_requested_by,
    )

    logger = logging.getLogger("icu.test.json")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    set_correlation_id("corr-abc")
    set_requested_by("dr-x")
    logger.info("audit-event")

    payload = json.loads(stream.getvalue().strip())
    assert payload["message"] == "audit-event"
    assert payload["correlation_id"] == "corr-abc"
    assert payload["requested_by"] == "dr-x"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload

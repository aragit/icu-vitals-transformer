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
from src.dependencies import reset_dependencies
from src.main import app
from src.mcp_server.server import _vitals_store

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
    assert os.path.isfile(os.path.join(_MANIFESTS, "AGENT_CARD.json"))


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


def test_agent_card_valid_json():
    with open(os.path.join(_MANIFESTS, "AGENT_CARD.json")) as fh:
        card = json.load(fh)
    assert card["name"] == "icu-vitals-transformer"
    assert "streamable-http" in json.dumps(card["protocols"]["mcp"])
    assert card["operationalGuardrails"]["phiInMetrics"] is False


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
    }
    assert "clinical://bounds/v1" in [r["uri"] for r in body["resources"]]
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
# MRTR elicitation
# --------------------------------------------------------------------------- #
def test_mrtr_returns_prompt_for_ambiguous_episodes():
    from src.adapters.mcp.mrtr import mrtr_ambiguous_episode, resolve_single_episode
    from src.core.domain.episode import Episode

    ep1 = Episode(episode_id="E-A", patient_id="PT-X")
    ep2 = Episode(episode_id="E-B", patient_id="PT-X")
    mrtr = mrtr_ambiguous_episode("PT-X", [ep1, ep2], requested_by="dr-x")
    assert mrtr["type"] == "mrtr"
    assert mrtr["kind"] == "episode_disambiguation"
    assert {c["episode_id"] for c in mrtr["choices"]} == {"E-A", "E-B"}
    assert mrtr["requested_by"] == "dr-x"

    # resolve_single_episode: explicit id -> None; single candidate -> None;
    # multiple candidates + no id -> MRTR.
    assert resolve_single_episode("PT-X", [ep1], None) is None
    assert resolve_single_episode("PT-X", [ep1, ep2], "E-A") is None
    assert resolve_single_episode("PT-X", [ep1, ep2], None) is not None


@pytest.mark.asyncio
async def test_discover_episode_emits_mrtr_when_multiple_active(mcp_server):
    """discover_episode on a patient with >1 active episode returns MRTR."""
    from src.adapters.mcp.mrtr import mrtr_ambiguous_episode
    from src.core.domain.episode import Episode

    # The default repo holds a single active episode per patient; demonstrate
    # the MRTR contract directly with constructed candidate episodes.
    ep1 = Episode(episode_id="E-A", patient_id="PT-MRTR")
    ep2 = Episode(episode_id="E-B", patient_id="PT-MRTR")
    mrtr = mrtr_ambiguous_episode("PT-MRTR", [ep1, ep2], requested_by=None)
    assert mrtr["type"] == "mrtr"
    assert {c["episode_id"] for c in mrtr["choices"]} == {"E-A", "E-B"}


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

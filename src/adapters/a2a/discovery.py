"""A2A agent-card discovery (REST driving adapter).

Serves a dynamically generated A2A agent card at the well-known path
``GET /.well-known/agent.json`` so multi-agent orchestrators can negotiate
capabilities before dispatching tasks. The card is built from ``src.config``
settings at runtime so the URL/port reflects the actual deployment, while
``manifests/AGENT_CARD.json`` is preserved as a static documentation template.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import settings

AGENT_CARD_PATH = Path(__file__).resolve().parents[3] / "manifests" / "AGENT_CARD.json"


def build_agent_card() -> dict[str, Any]:
    """Build the A2A agent card dynamically from runtime settings.

    The ``url`` and protocol endpoints are derived from ``settings.host`` and
    ``settings.port`` so the card reflects the actual deployment rather than a
    hardcoded localhost address. All other fields are sourced from the static
    template (``manifests/AGENT_CARD.json``) to preserve the full capability
    matrix (skills, operational guardrails, security schemes, etc.).
    """
    card = load_agent_card()
    host = settings.host
    port = settings.port
    base_url = f"http://{host}:{port}"
    card["url"] = base_url
    card["protocols"]["mcp"]["endpoints"]["streamable_http"] = f"{base_url}/mcp"
    card["protocols"]["rest"]["base_url"] = base_url
    return card


def load_agent_card() -> dict[str, Any]:
    """Load the static agent card template from ``manifests/AGENT_CARD.json``.

    This loader is retained for tests and documentation that reference the
    static manifest; runtime endpoints use ``build_agent_card`` instead.
    """
    with AGENT_CARD_PATH.open("r", encoding="utf-8") as handle:
        return dict(json.load(handle))

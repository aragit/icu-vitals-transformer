"""A2A agent-card discovery (REST driving adapter).

Serves the manifest ``AGENT_CARD.json`` at the A2A discovery well-known path
``GET /.well-known/agent.json`` so multi-agent orchestrators can negotiate
capabilities before dispatching tasks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

AGENT_CARD_PATH = Path(__file__).resolve().parents[3] / "manifests" / "AGENT_CARD.json"


def load_agent_card() -> dict[str, Any]:
    """Load and return the A2A agent card from ``manifests/AGENT_CARD.json``."""
    with AGENT_CARD_PATH.open("r", encoding="utf-8") as handle:
        return dict(json.load(handle))

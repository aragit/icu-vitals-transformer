"""Agent-to-Agent (A2A) translation adapter (driving adapter).

Thin facade that exposes the hex core as an A2A-capable agent:

* `GET /.well-known/agent.json` serves the manifest agent card.
* `POST /a2a/tasks` accepts an incoming A2A-style Task, dispatches the requested
  action to ``ClinicalAssessmentService``, and packages the result into a
  standard A2A Artifact payload carrying the mandated ``_meta`` envelope.

The A2A surface is **feature-flagged** behind ``settings.a2a_enabled`` and
is mounted unconditionally on the FastAPI app but gated at the endpoint level so
the enabled/disabled behaviour is directly testable without rebuilding the app
(equivalent to conditional mounting, but hermetic for CI). This layer lives
entirely under ``src/adapters/`` — the hex core (``src/core/``,
``src/ports/``) is left untouched.
"""

from __future__ import annotations

from src.adapters.a2a.discovery import load_agent_card
from src.adapters.a2a.task_handler import A2ATaskHandler

__all__ = ["load_agent_card", "A2ATaskHandler"]

"""Mid-Flight Request To Re-ask (MRTR) elicitation helper (MCP adapter).

When an inbound tool call omits ``episode_id`` and a patient has **multiple**
active episodes, silently picking one would be unsafe. Instead the adapter
returns a structured MRTR payload prompting the caller agent to disambiguate.

The decision logic is intentionally pure (a function of the candidate episode
list) so it is trivially unit-testable without spinning up FastMCP.
"""

from __future__ import annotations

from typing import Any

_MRTR_TYPE = "mrtr"
_MRTR_KIND = "episode_disambiguation"


def mrtr_ambiguous_episode(
    patient_id: str,
    candidates: list[Any],
    *,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Build an MRTR prompt when ``episode_id`` is ambiguously resolvable."""
    choices = [
        {
            "episode_id": getattr(c, "episode_id", str(getattr(c, "id", c))),
            "state": getattr(c, "state", None),
            "created_at": getattr(c, "created_at", None),
        }
        for c in candidates
    ]
    return {
        "type": _MRTR_TYPE,
        "kind": _MRTR_KIND,
        "message": (
            f"Patient '{patient_id}' has multiple active episodes; "
            "please specify the target episode_id."
        ),
        "patient_id": patient_id,
        "choices": choices,
        "requested_by": requested_by,
    }


def resolve_single_episode(
    patient_id: str,
    candidates: list[Any],
    episode_id: str | None,
) -> dict[str, Any] | None:
    """Return an MRTR payload iff ``episode_id`` is needed but ambiguous."""
    if episode_id is not None:
        return None
    if len(candidates) <= 1:
        return None
    return mrtr_ambiguous_episode(patient_id, candidates)


__all__ = ["mrtr_ambiguous_episode", "resolve_single_episode"]

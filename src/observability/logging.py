"""Structured JSON logging for the ICU Vitals Transformer (observability).

Configures stdlib logging to emit single-line JSON records enriched with
``correlation_id``, ``patient_id`` and ``episode_id`` context fields captured
from ``contextvars`` so request-scoped tracing data follows every log line
without threading parameters through call sites.

Identifying fields are logged (never used as metric labels) — this is the
privacy-compliant channel for PHI-adjacent correlation.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
patient_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "patient_id", default=""
)
episode_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "episode_id", default=""
)
requested_by_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "requested_by", default=""
)


def set_correlation_id(value: str) -> None:
    """Bind a correlation ID for the current async/sync context."""
    correlation_id_var.set(value)


def set_patient_context(patient_id: str, episode_id: str | None = None) -> None:
    """Bind patient/episode context for the current execution context."""
    patient_id_var.set(patient_id)
    if episode_id is not None:
        episode_id_var.set(episode_id)


def set_requested_by(principal: str) -> None:
    """Bind the requesting principal (``sub``/``requested_by``) for audit logs."""
    requested_by_var.set(principal)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get() or None,
            "patient_id": patient_id_var.get() or None,
            "episode_id": episode_id_var.get() or None,
            "requested_by": requested_by_var.get() or None,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Install the JSON handler on the root logger (idempotent)."""
    root = logging.getLogger()
    already_installed = any(
        isinstance(getattr(h, "formatter", None), JsonFormatter) for h in root.handlers
    )
    if not already_installed:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)
    return root

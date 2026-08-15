"""Deterministic severity / risk-tier classification (Core domain governance).

Core Isolation invariant: pure Python + pydantic only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Phase 0 tiers: 0-2 NORMAL, 3-4 WARNING, 5-6 ALERT, >=7 EMERGENCY.
WARNING_THRESHOLD: int = 3
ALERT_THRESHOLD: int = 5
EMERGENCY_THRESHOLD: int = 7


def severity_from_score(score: float, trend: str = "stable") -> str:
    """Classify severity from a DDS score and optional trend.

    Deterministic mapping — no ML, no thresholds to tune. A ``critical`` trend
    overrides any score to EMERGENCY.
    """
    if score >= EMERGENCY_THRESHOLD or trend == "critical":
        severity = "EMERGENCY"
    elif score >= ALERT_THRESHOLD:
        severity = "ALERT"
    elif score >= WARNING_THRESHOLD:
        severity = "WARNING"
    else:
        severity = "NORMAL"

    logger.debug("Severity: score=%s, trend=%s -> %s", score, trend, severity)
    return severity


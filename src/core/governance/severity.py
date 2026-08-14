"""Deterministic severity / risk-tier classification (Core domain governance).

Core Isolation invariant: pure Python + pydantic only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Score -> risk tier. Baseline (Phase 0) tiers:
#   0-2  NORMAL, 3-4 WARNING, 5-6 ALERT, >=7 EMERGENCY.
WARNING_THRESHOLD: int = 3
ALERT_THRESHOLD: int = 5
EMERGENCY_THRESHOLD: int = 7

# Risk-tier aliases used by reporting adapters (future LOW/MEDIUM/HIGH/CRITICAL
# mapping documented in docs/BASELINE.md §6).
RISK_TIERS: dict[str, str] = {
    "NORMAL": "NORMAL",
    "WARNING": "WARNING",
    "ALERT": "ALERT",
    "EMERGENCY": "EMERGENCY",
    "CRITICAL": "EMERGENCY",
}


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


def risk_tier(score: float, trend: str = "stable") -> str:
    """Map a score to a generic risk tier (normalised casing)."""
    return RISK_TIERS[severity_from_score(score, trend)]

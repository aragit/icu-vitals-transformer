"""Deterministic severity classification."""

from loguru import logger


def severity_from_score(score: float, trend: str = "stable") -> str:
    """Classify severity from deterioration score and trend.

    Deterministic mapping — no ML, no thresholds to tune.
    """
    if score >= 7 or trend == "critical":
        severity = "EMERGENCY"
    elif score >= 5:
        severity = "ALERT"
    elif score >= 3:
        severity = "WARNING"
    else:
        severity = "NORMAL"

    logger.debug(f"Severity classification: score={score}, trend={trend} -> {severity}")
    return severity

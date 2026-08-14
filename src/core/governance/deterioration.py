"""Deterministic Deterioration Score (DDS) computation (Core domain governance).

Core Isolation invariant: pure Python + pydantic only.

DDS is the Phase 1 rename of the Phase 0 NEWS2-inspired ``compute_deterioration_index``.
It is **NOT** the standard NEWS2 scale: thresholds and point values loosely
follow NEWS2 but deviate (e.g. some cut points and the AVPU weighting differ).
The composite is intentionally deterministic and bounded.

Maximum achievable DDS = ``DDS_MAX_SCORE`` (20):
  RR 3 + SpO2 3 + SBP 3 + HR 3 + Temp 3 + AVPU 3 + trend 2.
"""

from __future__ import annotations

import logging

from src.core.domain.vitals import VitalSignsWindow

logger = logging.getLogger(__name__)

DDS_MAX_SCORE: int = 20


def compute_dds(
    vitals: VitalSignsWindow,
    trend: str = "stable",
) -> tuple[float, list[str]]:
    """Compute the Deterministic Deterioration Score and contributing factors.

    Returns:
        ``(score, contributing_factors)`` with ``0 <= score <= DDS_MAX_SCORE``.
    """
    score = 0.0
    factors: list[str] = []

    rr = vitals.respiratory_rate
    if rr is not None:
        if rr < 8 or rr > 25:
            score += 3
            factors.append("respiratory_rate_critical")
        elif rr > 20:
            score += 2
            factors.append("respiratory_rate_elevated")

    spo2 = vitals.spo2
    if spo2 is not None:
        if spo2 < 91:
            score += 3
            factors.append("spo2_severe")
        elif spo2 < 93:
            score += 2
            factors.append("spo2_moderate")
        elif spo2 < 95:
            score += 1
            factors.append("spo2_mild")

    sbp = vitals.systolic_bp
    if sbp is not None:
        if sbp < 90 or sbp > 220:
            score += 3
            factors.append("systolic_bp_critical")
        elif sbp < 100:
            score += 2
            factors.append("systolic_bp_low")

    hr = vitals.heart_rate
    if hr is not None:
        if hr < 40 or hr > 130:
            score += 3
            factors.append("heart_rate_critical")
        elif hr > 110:
            score += 2
            factors.append("heart_rate_elevated")

    temp = vitals.temperature
    if temp is not None:
        if temp < 35.0:
            score += 3
            factors.append("hypothermia")
        elif temp > 39.0:
            score += 2
            factors.append("hyperthermia")

    avpu = vitals.avpu
    if avpu is not None and avpu != "A":
        score += 3
        factors.append(f"altered_consciousness_{avpu}")

    if trend == "rapidly_deteriorating":
        score += 2
        factors.append("rapid_deterioration_trend")

    score = min(score, float(DDS_MAX_SCORE))
    logger.debug("DDS for %s: %s, factors: %s", vitals.patient_id, score, factors)
    return score, factors


# Backward-compatible alias preserving the Phase 0 public name.
compute_deterioration_index = compute_dds

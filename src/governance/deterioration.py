"""NEWS2-inspired deterioration index computation."""


from loguru import logger

from src.models.vitals import VitalSignsWindow


def compute_deterioration_index(vitals: VitalSignsWindow, trend: str = "stable") -> tuple[float, list[str]]:
    """Compute composite deterioration score from vital signs.

    Returns:
        (score, contributing_factors)
    """
    score = 0.0
    factors = []

    # Respiratory rate
    rr = vitals.respiratory_rate
    if rr is not None:
        if rr < 8 or rr > 25:
            score += 3
            factors.append("respiratory_rate_critical")
        elif rr > 20:
            score += 2
            factors.append("respiratory_rate_elevated")

    # SpO2
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

    # Systolic BP
    sbp = vitals.systolic_bp
    if sbp is not None:
        if sbp < 90 or sbp > 220:
            score += 3
            factors.append("systolic_bp_critical")
        elif sbp < 100:
            score += 2
            factors.append("systolic_bp_low")

    # Heart rate
    hr = vitals.heart_rate
    if hr is not None:
        if hr < 40 or hr > 130:
            score += 3
            factors.append("heart_rate_critical")
        elif hr > 110:
            score += 2
            factors.append("heart_rate_elevated")

    # Temperature
    temp = vitals.temperature
    if temp is not None:
        if temp < 35.0:
            score += 3
            factors.append("hypothermia")
        elif temp > 39.0:
            score += 2
            factors.append("hyperthermia")

    # Consciousness (AVPU)
    avpu = vitals.avpu
    if avpu is not None and avpu != "A":
        score += 3
        factors.append(f"altered_consciousness_{avpu}")

    # Trend component
    if trend == "rapidly_deteriorating":
        score += 2
        factors.append("rapid_deterioration_trend")

    logger.debug(f"Deterioration index for {vitals.patient_id}: {score}, factors: {factors}")
    return score, factors

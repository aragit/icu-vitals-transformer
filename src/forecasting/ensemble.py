"""Multi-horizon ensemble: aggregate forecasts into deterioration index."""

from loguru import logger

from src.observability.metrics import FORECASTS_GENERATED, FORECAST_LATENCY, ASSESSMENTS_TOTAL

from src.models.vitals import VitalSignsWindow
from src.models.forecast import ForecastResult, DeteriorationAssessment
from src.forecasting.backends import DeterministicBackend, ForecastBackend
from src.governance.deterioration import compute_deterioration_index
from src.governance.severity import severity_from_score


# Horizon weights: 1h (0.5), 4h (0.3), 12h (0.2)
HORIZON_WEIGHTS = {60: 0.5, 240: 0.3, 720: 0.2}


def ensemble_forecast(
    current_window: VitalSignsWindow,
    trend_per_hour: dict[str, float] | None = None,
    backend: ForecastBackend | None = None,
) -> list[ForecastResult]:
    """Generate multi-horizon forecasts and attach governance classification.

    Args:
        current_window: Latest aggregated vital signs
        trend_per_hour: Optional trend overrides per vital type
        backend: ForecastBackend implementation (default: DeterministicBackend)

    Returns:
        List of ForecastResult for each horizon (60, 240, 720 min)
    """
    backend = backend or DeterministicBackend()
    horizons = [60, 240, 720]
    results = []

    for horizon in horizons:
        with FORECAST_LATENCY.time():
            forecast = backend.forecast(current_window, horizon, trend_per_hour)
        score, factors = compute_deterioration_index(forecast.forecasted_vitals)
        severity = severity_from_score(score)

        forecast.deterioration_index = round(score, 2)
        forecast.severity = severity
        FORECASTS_GENERATED.inc()

        results.append(forecast)
        logger.debug(f"Horizon {horizon}min: score={score}, severity={severity}")

    return results


def ensemble_deterioration_index(forecasts: list[ForecastResult]) -> DeteriorationAssessment:
    """Compute weighted ensemble deterioration index from multi-horizon forecasts.

    Args:
        forecasts: List of ForecastResult (typically 3 horizons)

    Returns:
        DeteriorationAssessment with ensemble score and severity
    """
    if not forecasts:
        raise ValueError("No forecasts provided for ensemble")

    patient_id = forecasts[0].patient_id
    weighted_score = 0.0
    all_factors = []
    max_severity = "NORMAL"

    severity_rank = {"NORMAL": 0, "WARNING": 1, "ALERT": 2, "EMERGENCY": 3}

    for forecast in forecasts:
        weight = HORIZON_WEIGHTS.get(forecast.horizon_minutes, 0.0)
        weighted_score += forecast.deterioration_index * weight

        # Collect unique factors
        _, factors = compute_deterioration_index(forecast.forecasted_vitals)
        for f in factors:
            if f not in all_factors:
                all_factors.append(f)

        # Track max severity
        if severity_rank.get(forecast.severity, 0) > severity_rank.get(max_severity, 0):
            max_severity = forecast.severity

    final_score = round(weighted_score, 2)

    ASSESSMENTS_TOTAL.inc()
    logger.info(f"Ensemble deterioration index for {patient_id}: {final_score} ({max_severity})")

    return DeteriorationAssessment(
        patient_id=patient_id,
        ensemble_score=final_score,
        severity=max_severity,
        contributing_factors=all_factors,
    )

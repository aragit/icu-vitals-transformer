"""FastAPI routes for vitals ingestion and forecasting."""

from fastapi import APIRouter, HTTPException

from src.ingestion.fhir_parser import parse_batch
from src.ingestion.windowing import window_vitals
from src.forecasting.ensemble import ensemble_forecast, ensemble_deterioration_index
from src.models.vitals import VitalIngestionRequest, VitalSignsWindow
from src.models.forecast import ForecastResult, DeteriorationAssessment
from src.mcp_server.server import _vitals_store

router = APIRouter(prefix="/vitals", tags=["vitals"])


@router.post("/ingest", response_model=VitalSignsWindow)
async def ingest_vitals(request: VitalIngestionRequest):
    """Ingest FHIR Observations and return windowed vitals."""
    parsed = parse_batch(request.observations)
    if not parsed:
        raise HTTPException(status_code=400, detail="No valid observations parsed")

    patient_id = parsed[0].get("patient_id", "unknown")
    if patient_id not in _vitals_store:
        _vitals_store[patient_id] = []
    _vitals_store[patient_id].extend(parsed)

    window = window_vitals(parsed, patient_id)
    if not window:
        raise HTTPException(status_code=400, detail="Could not window vitals")

    return window


@router.get("/current/{patient_id}", response_model=VitalSignsWindow)
async def get_current_vitals(patient_id: str):
    """Get latest windowed vitals for a patient."""
    records = _vitals_store.get(patient_id, [])
    if not records:
        raise HTTPException(status_code=404, detail=f"No vitals found for {patient_id}")

    window = window_vitals(records, patient_id)
    if not window:
        raise HTTPException(status_code=400, detail="Could not window vitals")

    return window


@router.get("/forecast/{patient_id}", response_model=list[ForecastResult])
async def get_forecast(patient_id: str):
    """Get multi-horizon forecast for a patient."""
    records = _vitals_store.get(patient_id, [])
    if not records:
        raise HTTPException(status_code=404, detail=f"No vitals found for {patient_id}")

    window = window_vitals(records, patient_id)
    if not window:
        raise HTTPException(status_code=400, detail="Could not window vitals")

    return ensemble_forecast(window)


@router.get("/deterioration/{patient_id}", response_model=DeteriorationAssessment)
async def get_deterioration(patient_id: str):
    """Get ensemble deterioration index for a patient."""
    records = _vitals_store.get(patient_id, [])
    if not records:
        raise HTTPException(status_code=404, detail=f"No vitals found for {patient_id}")

    window = window_vitals(records, patient_id)
    if not window:
        raise HTTPException(status_code=400, detail="Could not window vitals")

    forecasts = ensemble_forecast(window)
    return ensemble_deterioration_index(forecasts)

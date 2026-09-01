from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import cost_service
from app.ml import anomaly, forecast
from app.schemas import AnomalyOut, ForecastOut

router = APIRouter(tags=["intelligence"])


@router.get("/forecast", response_model=list[ForecastOut])
def get_forecast(
    site_id: str | None = None,
    type: str | None = None,
    weeks: int = 4,
    db: Session = Depends(get_db),
):
    rows = forecast.read(db, site_id=site_id, equipment_type=type, weeks=weeks)
    if not rows:  # first call after boot -- generate on demand
        forecast.generate(db, horizon_weeks=weeks)
        rows = forecast.read(db, site_id=site_id, equipment_type=type, weeks=weeks)
    return rows


@router.post("/forecast/run")
def run_forecast(weeks: int = 4, db: Session = Depends(get_db)):
    records = forecast.generate(db, horizon_weeks=weeks)
    return {"generated": len(records)}


@router.get("/forecast/shortages")
def shortages(db: Session = Depends(get_db)):
    return forecast.shortages(db)


@router.get("/anomalies", response_model=list[AnomalyOut])
def anomalies(limit: int = 100, all_scores: bool = False, db: Session = Depends(get_db)):
    return anomaly.list_anomalies(db, limit=limit, only_anomalies=not all_scores)


@router.post("/anomalies/scan")
def run_anomaly_scan(db: Session = Depends(get_db)):
    return anomaly.scan(db)


@router.get("/optimize/recommendations")
def recommendations(db: Session = Depends(get_db)):
    return cost_service.recommendations(db)


@router.get("/optimize/idle-cost")
def idle_cost(days: int = 30, db: Session = Depends(get_db)):
    return cost_service.idle_cost_report(db, days=days)


@router.get("/optimize/maintenance")
def maintenance(db: Session = Depends(get_db)):
    return cost_service.maintenance_risk(db)


@router.get("/optimize/savings")
def savings(db: Session = Depends(get_db)):
    return cost_service.savings_summary(db)

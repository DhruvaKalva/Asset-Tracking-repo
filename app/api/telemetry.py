from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import telemetry_service
from app.schemas import LocationIn, TelemetryBatchIn, TelemetryTickIn

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry", status_code=202)
def ingest(body: TelemetryTickIn, db: Session = Depends(get_db)):
    row = telemetry_service.ingest_tick(
        db,
        equipment_id=body.equipment_id.upper(),
        engine_hours=body.engine_hours,
        idle_hours=body.idle_hours,
        fuel_litres=body.fuel_litres,
        lat=body.lat,
        lng=body.lng,
        occurred_at=body.occurred_at,
        idempotency_key=body.idempotency_key,
    )
    return {
        "equipment_id": row.equipment_id,
        "day": str(row.day),
        "engine_hours": row.engine_hours,
        "idle_hours": row.idle_hours,
    }


@router.post("/telemetry/batch", status_code=202)
def ingest_batch(body: TelemetryBatchIn, db: Session = Depends(get_db)):
    count = telemetry_service.ingest_batch(db, [t.model_dump() for t in body.ticks])
    return {"ingested": count}


@router.post("/telemetry/location", status_code=202)
def location(body: LocationIn, db: Session = Depends(get_db)):
    telemetry_service.record_location(db, body.equipment_id.upper(), body.lat, body.lng)
    return {"ok": True}


@router.get("/usage")
def usage(
    group_by: str = Query("asset", pattern="^(asset|site|type)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return telemetry_service.usage_summary(db, group_by=group_by, date_from=date_from, date_to=date_to)


@router.get("/usage/{equipment_id}")
def asset_usage(equipment_id: str, days: int = 90, db: Session = Depends(get_db)):
    return telemetry_service.asset_usage(db, equipment_id.upper(), days=days)


@router.get("/kpis")
def kpis(days: int = 30, db: Session = Depends(get_db)):
    return telemetry_service.fleet_kpis(db, days=days)

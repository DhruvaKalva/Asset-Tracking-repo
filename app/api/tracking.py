"""Live tracking: map snapshot, breadcrumb trails, geofence state."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import tracking

router = APIRouter(tags=["tracking"])


@router.get("/map")
def map_snapshot(db: Session = Depends(get_db)):
    """Everything a map needs in one call: asset markers plus site geofence rings."""
    return tracking.live_positions(db)


@router.get("/assets/{equipment_id}/track")
def asset_track(
    equipment_id: str,
    hours: int = Query(24, ge=1, le=720, description="Look-back window"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """Breadcrumb trail, replayed from the event log. Oldest point first."""
    return tracking.track(db, equipment_id, hours=hours, limit=limit)


@router.get("/geofence/breaches")
def breaches(db: Session = Depends(get_db)):
    """On-rent assets currently outside their assigned site's radius."""
    return tracking.geofence_breaches(db)

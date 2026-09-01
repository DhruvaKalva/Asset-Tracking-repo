from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import alert_service
from app.schemas import AlertOut

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    severity: str | None = None,
    kind: str | None = None,
    equipment_id: str | None = None,
    unresolved: bool = True,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    return alert_service.list_alerts(
        db,
        severity=severity,
        kind=kind,
        equipment_id=equipment_id,
        unresolved_only=unresolved,
        limit=limit,
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(alert_id: int, actor: str | None = None, db: Session = Depends(get_db)):
    return alert_service.acknowledge(db, alert_id, actor)


@router.post("/alerts/scan")
def run_scan(db: Session = Depends(get_db)):
    """Manual trigger for the overdue scan -- handy on stage."""
    return alert_service.scan_overdue(db)

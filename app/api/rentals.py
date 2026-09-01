from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import rental_service
from app.schemas import (
    AssignOperatorIn,
    CheckInIn,
    CheckOutIn,
    EquipmentOut,
    RentalOut,
)

router = APIRouter(tags=["rentals"])


@router.post("/checkout", response_model=RentalOut, status_code=201)
def check_out(body: CheckOutIn, db: Session = Depends(get_db)):
    """Scan -> assign -> go. Accepts QR payload, RFID tag, or a typed equipment id."""
    return rental_service.check_out(
        db,
        scan_payload=body.scan_payload,
        site_id=body.site_id,
        operator_id=body.operator_id,
        expected_check_in_date=body.expected_check_in_date,
        actor=body.actor,
        notes=body.notes,
        client_idempotency_key=body.idempotency_key,
    )


@router.post("/checkin", response_model=RentalOut)
def check_in(body: CheckInIn, db: Session = Depends(get_db)):
    return rental_service.check_in(
        db,
        scan_payload=body.scan_payload,
        actor=body.actor,
        notes=body.notes,
        client_idempotency_key=body.idempotency_key,
    )


@router.post("/assets/{equipment_id}/operator", response_model=RentalOut)
def assign_operator(equipment_id: str, body: AssignOperatorIn, db: Session = Depends(get_db)):
    return rental_service.assign_operator(db, equipment_id.upper(), body.operator_id, body.actor)


@router.get("/rentals", response_model=list[RentalOut])
def rentals(equipment_id: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    return rental_service.rental_history(db, equipment_id, limit)


@router.get("/equipment/available", response_model=list[EquipmentOut])
def available(type: str | None = None, db: Session = Depends(get_db)):
    return rental_service.available_equipment(db, type)


@router.post("/scan/resolve")
def resolve_scan(payload: dict, db: Session = Depends(get_db)):
    """Lets the scanner screen show what it just read before committing."""
    equipment_id, source = rental_service.resolve_asset(db, payload.get("scan_payload", ""))
    return {"equipment_id": equipment_id, "resolved_via": source}

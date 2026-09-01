"""Fleet onboarding: add equipment, sites and operators."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import registry
from app.schemas import (
    EquipmentCreate,
    EquipmentOut,
    EquipmentUpdate,
    OperatorCreate,
    OperatorOut,
    ServiceLogIn,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)

router = APIRouter(tags=["registry"])


@router.post("/equipment", response_model=EquipmentOut, status_code=201)
def add_equipment(body: EquipmentCreate, db: Session = Depends(get_db)):
    """Register a machine. The ID, QR payload and RFID tag are minted for you."""
    return registry.create_equipment(db, **body.model_dump())


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
def edit_equipment(equipment_id: str, body: EquipmentUpdate, db: Session = Depends(get_db)):
    payload = body.model_dump(exclude_unset=True)
    actor = payload.pop("actor", None)
    return registry.update_equipment(db, equipment_id, actor=actor, **payload)


@router.get("/equipment/{equipment_id}/label")
def print_label(equipment_id: str, db: Session = Depends(get_db)):
    """What to encode on the sticker the yard prints for this asset."""
    equipment = registry.get_equipment(db, equipment_id)
    return {
        "equipment_id": equipment.equipment_id,
        "qr_payload": equipment.qr_payload,
        "rfid_tag": equipment.rfid_tag,
        "type": equipment.type,
        "model": equipment.model,
    }


@router.post("/equipment/{equipment_id}/service", response_model=EquipmentOut)
def log_service(equipment_id: str, body: ServiceLogIn, db: Session = Depends(get_db)):
    """Reset the maintenance clock once a service is actually done."""
    return registry.log_service(db, equipment_id, notes=body.notes, actor=body.actor)


@router.post("/equipment/{equipment_id}/retire")
def retire(equipment_id: str, actor: str | None = None, db: Session = Depends(get_db)):
    """Retire, never delete -- the event log has to stay whole."""
    return registry.retire_equipment(db, equipment_id, actor)


@router.post("/sites", response_model=SiteOut, status_code=201)
def add_site(body: SiteCreate, db: Session = Depends(get_db)):
    return registry.create_site(db, **body.model_dump())


@router.patch("/sites/{site_id}", response_model=SiteOut)
def edit_site(site_id: str, body: SiteUpdate, db: Session = Depends(get_db)):
    return registry.update_site(db, site_id, **body.model_dump(exclude_unset=True))


@router.post("/operators", response_model=OperatorOut, status_code=201)
def add_operator(body: OperatorCreate, db: Session = Depends(get_db)):
    return registry.create_operator(db, **body.model_dump())


@router.get("/registry/counts")
def counts(db: Session = Depends(get_db)):
    return registry.fleet_counts(db)

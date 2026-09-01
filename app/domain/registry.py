"""Fleet registry: onboard equipment, sites and operators.

A dealer buys machines and opens sites after the software ships, so none of this
can live in a seed script. Creating an asset also mints its QR payload and RFID
tag, because an asset nobody can scan is not in the system in any useful sense.
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import projections
from app.domain.errors import Conflict, NotFound
from app.domain.events import record_event
from app.models import Equipment, EventType, Mobility, Operator, Rental, RentalStatus, Site

ID_PATTERN = re.compile(r"^EQX(\d+)$")
DEFAULT_SERVICE_INTERVAL = 500.0


def next_equipment_id(db: Session) -> str:
    """EQX1021, EQX1022, ... continuing the existing series."""
    highest = 1000
    for eid in db.scalars(select(Equipment.equipment_id)):
        match = ID_PATTERN.match(eid)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"EQX{highest + 1}"


def mint_tags(equipment_id: str) -> tuple[str, str]:
    """QR payload is printed on the sticker; the RFID tag is the gate's view."""
    return f"CAT-QR-{equipment_id}", f"RFID-{equipment_id[-4:]}-{random.randint(1000, 9999)}"


def create_equipment(
    db: Session,
    type: str,
    model: str | None = None,
    equipment_id: str | None = None,
    rental_rate_per_hour: float = 0.0,
    service_interval_hours: float = DEFAULT_SERVICE_INTERVAL,
    lifetime_engine_hours: float = 0.0,
    hours_at_last_service: float | None = None,
    qr_payload: str | None = None,
    rfid_tag: str | None = None,
    mobility: str = Mobility.MOVABLE.value,
    home_site_id: str | None = None,
    actor: str | None = None,
) -> Equipment:
    equipment_id = (equipment_id or next_equipment_id(db)).upper().strip()

    if db.get(Equipment, equipment_id) is not None:
        raise Conflict(f"{equipment_id} already exists")
    if not type.strip():
        raise Conflict("equipment type is required")
    if rental_rate_per_hour < 0 or service_interval_hours <= 0:
        raise Conflict("rate must be >= 0 and service interval > 0")

    mobility = (mobility or Mobility.MOVABLE.value).upper().strip()
    if mobility not in {m.value for m in Mobility}:
        raise Conflict(f"mobility must be MOVABLE or FIXED, got {mobility}")

    home_site_id = (home_site_id or "").upper().strip() or None
    if home_site_id is not None and db.get(Site, home_site_id) is None:
        raise Conflict(f"unknown site {home_site_id}")
    # A fixed asset without a site has no location and no way to be found --
    # it would sit on the dashboard as permanently unaccounted for.
    if mobility == Mobility.FIXED.value and home_site_id is None:
        raise Conflict("a fixed asset must be installed at a site")

    minted_qr, minted_rfid = mint_tags(equipment_id)
    qr_payload = qr_payload or minted_qr
    rfid_tag = rfid_tag or minted_rfid

    if db.scalar(select(Equipment).where(Equipment.qr_payload == qr_payload)):
        raise Conflict(f"QR payload {qr_payload} is already in use")
    if db.scalar(select(Equipment).where(Equipment.rfid_tag == rfid_tag)):
        raise Conflict(f"RFID tag {rfid_tag} is already in use")

    equipment = Equipment(
        equipment_id=equipment_id,
        type=type.strip(),
        model=(model or "").strip() or None,
        qr_payload=qr_payload,
        rfid_tag=rfid_tag,
        rental_rate_per_hour=rental_rate_per_hour,
        lifetime_engine_hours=lifetime_engine_hours,
        # A used machine bought mid-life is not overdue for service on day one.
        hours_at_last_service=(
            lifetime_engine_hours if hours_at_last_service is None else hours_at_last_service
        ),
        service_interval_hours=service_interval_hours,
        mobility=mobility,
        home_site_id=home_site_id,
    )
    db.add(equipment)
    db.flush()

    record_event(
        db,
        equipment_id,
        EventType.MAINTENANCE_LOGGED,
        payload={
            "action": "ASSET_REGISTERED",
            "type": equipment.type,
            "model": equipment.model,
            "qr_payload": qr_payload,
            "rfid_tag": rfid_tag,
            "rental_rate_per_hour": rental_rate_per_hour,
            "mobility": mobility,
            "home_site_id": home_site_id,
        },
        source="manual",
        actor=actor,
    )
    # Give it a projection row immediately so it shows on the dashboard as AVAILABLE.
    projections.recompute_state(db, equipment_id)
    db.commit()
    return equipment


def get_equipment(db: Session, equipment_id: str) -> Equipment:
    equipment = db.get(Equipment, equipment_id.upper())
    if equipment is None:
        raise NotFound(f"unknown equipment {equipment_id}")
    return equipment


def update_equipment(db: Session, equipment_id: str, actor: str | None = None, **fields) -> Equipment:
    equipment = db.get(Equipment, equipment_id.upper())
    if equipment is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    editable = {
        "type",
        "model",
        "rental_rate_per_hour",
        "service_interval_hours",
        "hours_at_last_service",
        "rfid_tag",
        "mobility",
        "home_site_id",
    }
    # Guard the same invariant the create path enforces.
    next_mobility = (fields.get("mobility") or equipment.mobility or Mobility.MOVABLE.value).upper()
    next_home = fields.get("home_site_id", equipment.home_site_id)
    if next_mobility == Mobility.FIXED.value and not next_home:
        raise Conflict("a fixed asset must be installed at a site")
    if fields.get("home_site_id") and db.get(Site, str(fields["home_site_id"]).upper()) is None:
        raise Conflict(f"unknown site {fields['home_site_id']}")

    changed = {}
    for key, value in fields.items():
        if key in editable and value is not None and getattr(equipment, key) != value:
            if key == "rfid_tag":
                clash = db.scalar(
                    select(Equipment).where(
                        Equipment.rfid_tag == value, Equipment.equipment_id != equipment.equipment_id
                    )
                )
                if clash is not None:
                    raise Conflict(f"RFID tag {value} is already in use")
            changed[key] = {"from": getattr(equipment, key), "to": value}
            setattr(equipment, key, value)

    if changed:
        record_event(
            db,
            equipment.equipment_id,
            EventType.MAINTENANCE_LOGGED,
            payload={"action": "ASSET_UPDATED", "changes": changed},
            source="manual",
            actor=actor,
        )
        projections.recompute_state(db, equipment.equipment_id)
    db.commit()
    return equipment


def log_service(db: Session, equipment_id: str, notes: str | None = None, actor: str | None = None) -> Equipment:
    """Reset the maintenance clock. Ends the DUE/HIGH risk state honestly."""
    equipment = db.get(Equipment, equipment_id.upper())
    if equipment is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    equipment.hours_at_last_service = equipment.lifetime_engine_hours
    record_event(
        db,
        equipment.equipment_id,
        EventType.MAINTENANCE_LOGGED,
        payload={
            "action": "SERVICE_COMPLETED",
            "at_engine_hours": equipment.lifetime_engine_hours,
            "notes": notes,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        source="manual",
        actor=actor,
    )
    db.commit()
    return equipment


def retire_equipment(db: Session, equipment_id: str, actor: str | None = None) -> dict:
    """Assets are retired, never deleted -- the event log has to stay whole."""
    equipment = db.get(Equipment, equipment_id.upper())
    if equipment is None:
        raise NotFound(f"unknown equipment {equipment_id}")
    if projections.open_rental(db, equipment.equipment_id) is not None:
        raise Conflict(f"{equipment.equipment_id} is on rent -- check it in before retiring")

    record_event(
        db,
        equipment.equipment_id,
        EventType.MAINTENANCE_LOGGED,
        payload={"action": "ASSET_RETIRED"},
        source="manual",
        actor=actor,
    )
    db.commit()
    return {"equipment_id": equipment.equipment_id, "retired": True}


# ---------------------------------------------------------------------------
# Sites and operators
# ---------------------------------------------------------------------------
def create_site(
    db: Session,
    site_id: str,
    name: str,
    region: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 5.0,
) -> Site:
    site_id = site_id.upper().strip()
    if db.get(Site, site_id) is not None:
        raise Conflict(f"site {site_id} already exists")
    if radius_km <= 0:
        raise Conflict("geofence radius must be greater than zero")
    if (lat is None) != (lng is None):
        raise Conflict("provide both lat and lng, or neither")

    site = Site(
        site_id=site_id, name=name.strip(), region=region, lat=lat, lng=lng, radius_km=radius_km
    )
    db.add(site)
    db.commit()
    return site


def update_site(db: Session, site_id: str, **fields) -> Site:
    site = db.get(Site, site_id.upper())
    if site is None:
        raise NotFound(f"unknown site {site_id}")
    for key in ("name", "region", "lat", "lng", "radius_km"):
        if fields.get(key) is not None:
            setattr(site, key, fields[key])
    db.commit()
    return site


def create_operator(
    db: Session,
    operator_id: str,
    name: str,
    certification: str | None = None,
    phone: str | None = None,
) -> Operator:
    operator_id = operator_id.upper().strip()
    if db.get(Operator, operator_id) is not None:
        raise Conflict(f"operator {operator_id} already exists")
    operator = Operator(
        operator_id=operator_id, name=name.strip(), certification=certification, phone=phone
    )
    db.add(operator)
    db.commit()
    return operator


def fleet_counts(db: Session) -> dict:
    return {
        "equipment": db.scalar(select(func.count(Equipment.equipment_id))) or 0,
        "sites": db.scalar(select(func.count(Site.site_id))) or 0,
        "operators": db.scalar(select(func.count(Operator.operator_id))) or 0,
        "open_rentals": db.scalar(
            select(func.count(Rental.rental_id)).where(
                Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value])
            )
        )
        or 0,
    }

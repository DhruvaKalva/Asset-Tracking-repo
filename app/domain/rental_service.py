"""Check-out / check-in. The core journey -- everything else hangs off it."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.scanner import ScanError, get_scanner
from app.domain import alert_service, projections
from app.domain.errors import Conflict, NotFound
from app.domain.events import find_by_idempotency_key, make_idempotency_key, record_event
from app.models import Equipment, EventType, Operator, Rental, RentalStatus, Site

DEFAULT_RENTAL_DAYS = 14


def resolve_asset(db: Session, scan_payload: str) -> tuple[str, str]:
    try:
        return get_scanner().resolve_with_source(db, scan_payload)
    except ScanError as exc:
        raise NotFound(str(exc)) from exc


def _replayed_rental(db: Session, key: str | None) -> Rental | None:
    """A scan the server already processed. Returns the rental it produced."""
    if not key:
        return None
    event = find_by_idempotency_key(db, key)
    if event is None:
        return None
    rental_id = (event.payload or {}).get("rental_id")
    if rental_id:
        rental = db.get(Rental, rental_id)
        if rental is not None:
            return rental
    return projections.open_rental(db, event.equipment_id) or db.scalar(
        select(Rental)
        .where(Rental.equipment_id == event.equipment_id)
        .order_by(Rental.rental_id.desc())
    )


def check_out(
    db: Session,
    scan_payload: str,
    site_id: str,
    operator_id: str | None = None,
    expected_check_in_date: date | None = None,
    actor: str | None = None,
    notes: str | None = None,
    client_idempotency_key: str | None = None,
) -> Rental:
    equipment_id, source = resolve_asset(db, scan_payload)

    # Replay check comes first: the offline queue retries, and a retry must get
    # back the rental it already created rather than a 409.
    replayed = _replayed_rental(db, client_idempotency_key)
    if replayed is not None:
        return replayed

    if projections.open_rental(db, equipment_id) is not None:
        raise Conflict(f"{equipment_id} is already checked out")

    if db.get(Site, site_id) is None:
        raise NotFound(f"unknown site {site_id}")
    if operator_id and db.get(Operator, operator_id) is None:
        raise NotFound(f"unknown operator {operator_id}")

    today = datetime.now(timezone.utc).date()
    expected = expected_check_in_date or today + timedelta(days=DEFAULT_RENTAL_DAYS)
    if expected < today:
        raise Conflict("expected return date is in the past")

    key = client_idempotency_key or make_idempotency_key(
        "CHECK_OUT", equipment_id, site_id, today
    )
    event = record_event(
        db,
        equipment_id,
        EventType.CHECK_OUT,
        payload={
            "site_id": site_id,
            "operator_id": operator_id,
            "expected_check_in_date": str(expected),
            "scan_payload": scan_payload,
            "notes": notes,
        },
        source=source,
        actor=actor,
        idempotency_key=key,
    )
    if event is None:  # replayed scan -- return what already exists
        existing = projections.open_rental(db, equipment_id)
        if existing:
            return existing
        raise Conflict("duplicate check-out request")

    rental = Rental(
        equipment_id=equipment_id,
        site_id=site_id,
        operator_id=operator_id,
        check_out_date=today,
        expected_check_in_date=expected,
        status=RentalStatus.ACTIVE.value,
        checkout_notes=notes,
    )
    db.add(rental)
    db.flush()

    projections.mark_seen(db, equipment_id)
    projections.recompute_state(db, equipment_id)
    db.commit()
    return rental


def check_in(
    db: Session,
    scan_payload: str,
    actor: str | None = None,
    notes: str | None = None,
    client_idempotency_key: str | None = None,
) -> Rental:
    equipment_id, source = resolve_asset(db, scan_payload)

    replayed = _replayed_rental(db, client_idempotency_key)
    if replayed is not None:
        return replayed

    rental = projections.open_rental(db, equipment_id)
    if rental is None:
        raise Conflict(f"{equipment_id} has no open rental to check in")

    today = datetime.now(timezone.utc).date()
    key = client_idempotency_key or make_idempotency_key(
        "CHECK_IN", equipment_id, rental.rental_id
    )
    event = record_event(
        db,
        equipment_id,
        EventType.CHECK_IN,
        payload={
            "rental_id": rental.rental_id,
            "site_id": rental.site_id,
            "days_out": (today - rental.check_out_date).days,
            "notes": notes,
        },
        source=source,
        actor=actor,
        idempotency_key=key,
    )
    if event is None:
        return rental

    rental.actual_check_in_date = today
    rental.status = RentalStatus.RETURNED.value
    rental.checkin_notes = notes
    db.flush()

    # A returned asset cannot still be overdue or unaccounted for.
    alert_service.resolve_open_alerts(
        db,
        equipment_id,
        kinds=["OVERDUE", "DUE_SOON", "UNASSIGNED_SITE", "STALE_PING", "GEOFENCE_BREACH"],
    )
    projections.mark_seen(db, equipment_id)
    projections.recompute_state(db, equipment_id)
    db.commit()
    return rental


def assign_operator(db: Session, equipment_id: str, operator_id: str, actor: str | None = None) -> Rental:
    rental = projections.open_rental(db, equipment_id)
    if rental is None:
        raise Conflict(f"{equipment_id} has no open rental")
    if db.get(Operator, operator_id) is None:
        raise NotFound(f"unknown operator {operator_id}")

    rental.operator_id = operator_id
    record_event(
        db,
        equipment_id,
        EventType.OPERATOR_ASSIGNED,
        payload={"operator_id": operator_id, "rental_id": rental.rental_id},
        source="manual",
        actor=actor,
    )
    alert_service.resolve_open_alerts(db, equipment_id, kinds=["NO_OPERATOR"])
    projections.recompute_state(db, equipment_id)
    db.commit()
    return rental


def rental_history(db: Session, equipment_id: str | None = None, limit: int = 200) -> list[Rental]:
    stmt = select(Rental).order_by(Rental.check_out_date.desc()).limit(limit)
    if equipment_id:
        stmt = stmt.where(Rental.equipment_id == equipment_id)
    return list(db.scalars(stmt))


def available_equipment(db: Session, equipment_type: str | None = None) -> list[Equipment]:
    stmt = select(Equipment)
    if equipment_type:
        stmt = stmt.where(Equipment.type == equipment_type)
    out = []
    for eq in db.scalars(stmt):
        if projections.open_rental(db, eq.equipment_id) is None:
            out.append(eq)
    return out

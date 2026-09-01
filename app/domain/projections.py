"""Read models derived from rentals + telemetry.

Nothing here is authoritative. Drop asset_current_state and call rebuild_all()
and you get it back -- that property is what makes new dashboard metrics cheap.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.bus import bus
from app.config import settings
from app.models import (
    AssetCurrentState,
    AssetEvent,
    AssetStatus,
    Equipment,
    Mobility,
    Rental,
    RentalStatus,
    Site,
    TelemetryDaily,
)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def open_rental(db: Session, equipment_id: str) -> Rental | None:
    return db.scalar(
        select(Rental)
        .where(
            Rental.equipment_id == equipment_id,
            Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value]),
        )
        .order_by(Rental.check_out_date.desc())
    )


def get_or_create_state(db: Session, equipment_id: str) -> AssetCurrentState:
    state = db.get(AssetCurrentState, equipment_id)
    if state is None:
        state = AssetCurrentState(equipment_id=equipment_id)
        db.add(state)
        db.flush()
    return state


def derive_status(
    rental: Rental | None,
    engine_hours: float,
    idle_hours: float,
    last_seen_at: datetime | None,
    today: date | None = None,
) -> tuple[str, dict]:
    """Status is derived, never stored by hand. Flags explain the verdict."""
    today = today or _today()
    flags: dict[str, bool | str] = {}

    if rental is None:
        return AssetStatus.AVAILABLE.value, flags

    total = engine_hours + idle_hours
    idle_ratio = idle_hours / total if total else 0.0
    flags["idle_ratio"] = round(idle_ratio, 3)

    stale = True
    if last_seen_at is not None:
        seen = last_seen_at if last_seen_at.tzinfo else last_seen_at.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - seen).total_seconds() / 3600
        stale = age_h > settings.stale_ping_hours
        flags["hours_since_ping"] = round(age_h, 1)

    if rental.expected_check_in_date and today > rental.expected_check_in_date:
        flags["days_overdue"] = (today - rental.expected_check_in_date).days
        return AssetStatus.OVERDUE.value, flags

    if rental.site_id is None:
        flags["unassigned_site"] = True
        return AssetStatus.UNACCOUNTED.value, flags

    if stale:
        flags["stale_ping"] = True
        return AssetStatus.UNACCOUNTED.value, flags

    if rental.operator_id is None:
        flags["no_operator"] = True

    if engine_hours <= 0 and idle_hours > 0:
        flags["zero_engine_hours"] = True
        return AssetStatus.IDLE.value, flags

    if idle_ratio > settings.idle_ratio_threshold:
        flags["excessive_idle"] = True
        return AssetStatus.IDLE.value, flags

    if engine_hours > 0:
        return AssetStatus.IN_USE.value, flags

    return AssetStatus.RENTED.value, flags


def derive_fixed_status(
    engine_hours: float,
    idle_hours: float,
    last_seen_at: datetime | None,
    home_site_id: str | None,
) -> tuple[str, dict]:
    """Status for installed plant, which is never rented.

    Kept separate from derive_status() rather than folded into it: half of that
    function is rental-shaped (overdue, expected return, operator assignment) and
    none of it means anything for a generator bolted to a slab. Sharing the code
    would mean threading "is there a rental" through every branch to reach the
    same answer.
    """
    flags: dict[str, bool | str | float] = {"fixed": True}

    total = engine_hours + idle_hours
    idle_ratio = idle_hours / total if total else 0.0
    flags["idle_ratio"] = round(idle_ratio, 3)

    if home_site_id is None:
        # create_equipment forbids this, but a hand-edited row could reach it.
        flags["unassigned_site"] = True
        return AssetStatus.UNACCOUNTED.value, flags

    if last_seen_at is not None:
        seen = last_seen_at if last_seen_at.tzinfo else last_seen_at.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - seen).total_seconds() / 3600
        flags["hours_since_ping"] = round(age_h, 1)
        if age_h > settings.stale_ping_hours:
            flags["stale_ping"] = True
            return AssetStatus.UNACCOUNTED.value, flags
    else:
        flags["stale_ping"] = True
        return AssetStatus.UNACCOUNTED.value, flags

    if total == 0:
        return AssetStatus.AVAILABLE.value, flags  # installed, nothing logged today

    if engine_hours <= 0:
        flags["zero_engine_hours"] = True
        return AssetStatus.IDLE.value, flags

    if idle_ratio > settings.idle_ratio_threshold:
        flags["excessive_idle"] = True
        return AssetStatus.IDLE.value, flags

    return AssetStatus.IN_USE.value, flags


def derive_last_seen(
    db: Session, equipment_id: str, latest_telemetry: TelemetryDaily | None
) -> datetime | None:
    """Recover 'last heard from' without the projection row.

    Without this, rebuilding asset_current_state would lose last_seen_at and
    every asset would immediately read as UNACCOUNTED -- which would make the
    read model non-rebuildable, and the whole event-sourced design a lie.
    """
    last_event = db.scalar(
        select(func.max(AssetEvent.occurred_at)).where(AssetEvent.equipment_id == equipment_id)
    )
    if last_event is not None:
        return last_event if last_event.tzinfo else last_event.replace(tzinfo=timezone.utc)
    if latest_telemetry is not None:
        # Day buckets have no clock time; treat them as an end-of-shift report.
        stamp = datetime.combine(latest_telemetry.day, time(18, 0), tzinfo=timezone.utc)
        return min(stamp, datetime.now(timezone.utc))
    return None


def recompute_state(db: Session, equipment_id: str, publish: bool = True) -> AssetCurrentState:
    state = get_or_create_state(db, equipment_id)
    rental = open_rental(db, equipment_id)
    today = _today()

    today_row = db.get(TelemetryDaily, (equipment_id, today))
    engine_h = today_row.engine_hours if today_row else 0.0
    idle_h = today_row.idle_hours if today_row else 0.0

    latest = db.scalar(
        select(TelemetryDaily)
        .where(TelemetryDaily.equipment_id == equipment_id)
        .order_by(TelemetryDaily.day.desc())
        .limit(1)
    )

    equipment = db.get(Equipment, equipment_id)
    is_fixed = equipment is not None and equipment.mobility == Mobility.FIXED.value

    state.rental_id = rental.rental_id if rental else None
    # Installed plant lives at its home site permanently; there is no rental to
    # read a site off, so without this it would project as site-less and every
    # fixed asset would read UNACCOUNTED.
    if is_fixed:
        state.site_id = equipment.home_site_id
    else:
        state.site_id = rental.site_id if rental else None
    state.operator_id = rental.operator_id if rental else None
    state.expected_check_in_date = rental.expected_check_in_date if rental else None
    state.engine_hours_today = engine_h
    state.idle_hours_today = idle_h
    state.utilization_pct = round(engine_h / (engine_h + idle_h) * 100, 1) if (engine_h + idle_h) else 0.0

    if state.last_seen_at is None:
        state.last_seen_at = derive_last_seen(db, equipment_id, latest)

    if latest is not None and latest.lat is not None:
        state.lat, state.lng = latest.lat, latest.lng
    elif state.site_id:
        # Falls back to the site's coordinates for a fixed asset that has never
        # reported a position, and for on-rent plant that has not pinged yet.
        site = db.get(Site, state.site_id)
        if site:
            state.lat, state.lng = site.lat, site.lng

    if is_fixed:
        status, flags = derive_fixed_status(engine_h, idle_h, state.last_seen_at, equipment.home_site_id)
    else:
        status, flags = derive_status(rental, engine_h, idle_h, state.last_seen_at, today)
    state.status = status
    state.health_flags = flags
    state.updated_at = datetime.now(timezone.utc)
    db.flush()

    if publish:
        bus.publish(
            "asset_state",
            {
                "equipment_id": equipment_id,
                "status": status,
                "site_id": state.site_id,
                "operator_id": state.operator_id,
                "utilization_pct": state.utilization_pct,
                "engine_hours_today": state.engine_hours_today,
                "idle_hours_today": state.idle_hours_today,
                "lat": state.lat,
                "lng": state.lng,
                "health_flags": flags,
            },
        )
    return state


def rebuild_all(db: Session) -> int:
    """Rebuild every projection from the underlying tables."""
    ids = list(db.scalars(select(Equipment.equipment_id)))
    for eid in ids:
        recompute_state(db, eid, publish=False)
    db.commit()
    return len(ids)


def mark_seen(db: Session, equipment_id: str, when: datetime | None = None) -> None:
    state = get_or_create_state(db, equipment_id)
    state.last_seen_at = when or datetime.now(timezone.utc)


def stale_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=settings.stale_ping_hours)

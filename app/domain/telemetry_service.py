"""Telemetry ingest + usage aggregation.

Ingest is an upsert into telemetry_daily keyed by (equipment_id, day), so the
same tick delivered twice by a retrying device does not inflate hours.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import projections
from app.domain.errors import NotFound
from app.domain.events import (
    find_by_idempotency_key,
    make_idempotency_key,
    record_event,
)
from app.models import Equipment, EventType, Rental, TelemetryDaily

HOURS_PER_DAY = 24.0


def ingest_tick(
    db: Session,
    equipment_id: str,
    engine_hours: float = 0.0,
    idle_hours: float = 0.0,
    fuel_litres: float = 0.0,
    lat: float | None = None,
    lng: float | None = None,
    day: date | None = None,
    occurred_at: datetime | None = None,
    source: str = "telemetry",
    idempotency_key: str | None = None,
    commit: bool = True,
) -> TelemetryDaily:
    """Add one increment of usage to a day bucket."""
    if db.get(Equipment, equipment_id) is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    occurred_at = occurred_at or datetime.now(timezone.utc)
    day = day or occurred_at.date()

    rental = projections.open_rental(db, equipment_id)
    site_id = rental.site_id if rental else None

    row = db.get(TelemetryDaily, (equipment_id, day))

    # A device retrying the same tick must not inflate the day's hours. Bail out
    # before touching the bucket, not after.
    if idempotency_key and find_by_idempotency_key(db, idempotency_key) is not None:
        return row or TelemetryDaily(equipment_id=equipment_id, day=day, site_id=site_id)

    if row is None:
        row = TelemetryDaily(equipment_id=equipment_id, day=day, site_id=site_id)
        db.add(row)
        db.flush()

    # Hard physical invariant: a machine cannot log more than 24 hours in a day.
    # Without this, a fast source (or a retrying one) produces impossible rows
    # that then poison every downstream z-score and utilisation figure.
    logged = (row.engine_hours or 0.0) + (row.idle_hours or 0.0)
    headroom = max(HOURS_PER_DAY - logged, 0.0)
    requested = engine_hours + idle_hours
    if requested > headroom:
        scale = headroom / requested if requested else 0.0
        engine_hours *= scale
        idle_hours *= scale
        fuel_litres *= scale

    row.engine_hours = round((row.engine_hours or 0.0) + engine_hours, 3)
    row.idle_hours = round((row.idle_hours or 0.0) + idle_hours, 3)
    row.fuel_litres = round((row.fuel_litres or 0.0) + fuel_litres, 3)
    if site_id:
        row.site_id = site_id
    if lat is not None:
        row.lat, row.lng = lat, lng

    record_event(
        db,
        equipment_id,
        EventType.TELEMETRY_TICK,
        payload={
            "engine_hours": engine_hours,
            "idle_hours": idle_hours,
            "fuel_litres": fuel_litres,
            "lat": lat,
            "lng": lng,
            "day": str(day),
        },
        source=source,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
        publish=False,  # state projection publishes the useful frame
    )

    # Lifetime hours drive the maintenance-risk score.
    equipment = db.get(Equipment, equipment_id)
    equipment.lifetime_engine_hours = round(
        (equipment.lifetime_engine_hours or 0.0) + engine_hours, 2
    )

    projections.mark_seen(db, equipment_id, occurred_at)
    projections.recompute_state(db, equipment_id)
    if commit:
        db.commit()
    return row


def ingest_batch(db: Session, ticks: list[dict]) -> int:
    """Bulk endpoint for real fleets. One commit for the whole batch."""
    count = 0
    for t in ticks:
        key = t.get("idempotency_key") or make_idempotency_key(
            "TICK", t.get("equipment_id"), t.get("occurred_at") or t.get("day")
        )
        ingest_tick(
            db,
            equipment_id=t["equipment_id"],
            engine_hours=float(t.get("engine_hours", 0.0)),
            idle_hours=float(t.get("idle_hours", 0.0)),
            fuel_litres=float(t.get("fuel_litres", 0.0)),
            lat=t.get("lat"),
            lng=t.get("lng"),
            occurred_at=t.get("occurred_at"),
            idempotency_key=key,
            commit=False,
        )
        count += 1
    db.commit()
    return count


def record_location(
    db: Session, equipment_id: str, lat: float, lng: float, occurred_at: datetime | None = None
) -> None:
    occurred_at = occurred_at or datetime.now(timezone.utc)
    day = occurred_at.date()
    row = db.get(TelemetryDaily, (equipment_id, day))
    if row is None:
        row = TelemetryDaily(equipment_id=equipment_id, day=day)
        db.add(row)
    row.lat, row.lng = lat, lng
    record_event(
        db,
        equipment_id,
        EventType.LOCATION_PING,
        payload={"lat": lat, "lng": lng},
        source="telemetry",
        occurred_at=occurred_at,
        publish=False,
    )
    projections.mark_seen(db, equipment_id, occurred_at)
    projections.recompute_state(db, equipment_id)
    db.commit()


# ---------------------------------------------------------------------------
# Usage summaries
# ---------------------------------------------------------------------------
def _window(days: int) -> tuple[date, date]:
    end = datetime.now(timezone.utc).date()
    return end - timedelta(days=days), end


def usage_rows(
    db: Session,
    equipment_id: str | None = None,
    site_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[TelemetryDaily]:
    if date_from is None or date_to is None:
        date_from, date_to = _window(90)
    stmt = select(TelemetryDaily).where(
        TelemetryDaily.day >= date_from, TelemetryDaily.day <= date_to
    )
    if equipment_id:
        stmt = stmt.where(TelemetryDaily.equipment_id == equipment_id)
    if site_id:
        stmt = stmt.where(TelemetryDaily.site_id == site_id)
    return list(db.scalars(stmt.order_by(TelemetryDaily.day)))


def _summarize(rows: list[TelemetryDaily]) -> dict:
    engine = sum(r.engine_hours for r in rows)
    idle = sum(r.idle_hours for r in rows)
    total = engine + idle
    days = len({r.day for r in rows})
    # Downtime is measured per asset-day, not per calendar day: a 20-asset
    # rollup over 30 days has 600 x 24 hours of capacity, not 30 x 24.
    asset_days = len({(r.equipment_id, r.day) for r in rows})
    return {
        "engine_hours": round(engine, 2),
        "idle_hours": round(idle, 2),
        "total_hours": round(total, 2),
        "utilization_pct": round(engine / total * 100, 1) if total else 0.0,
        "idle_ratio": round(idle / total, 3) if total else 0.0,
        "operating_days": days,
        "asset_days": asset_days,
        "downtime_hours": round(max(asset_days * HOURS_PER_DAY - total, 0), 2),
        "fuel_litres": round(sum(r.fuel_litres for r in rows), 2),
    }


def usage_summary(
    db: Session,
    group_by: str = "asset",
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """group_by: asset | site | type"""
    rows = usage_rows(db, date_from=date_from, date_to=date_to)
    types = {e.equipment_id: e.type for e in db.scalars(select(Equipment))}

    buckets: dict[str, list[TelemetryDaily]] = {}
    for r in rows:
        if group_by == "site":
            key = r.site_id or "UNASSIGNED"
        elif group_by == "type":
            key = types.get(r.equipment_id, "UNKNOWN")
        else:
            key = r.equipment_id
        buckets.setdefault(key, []).append(r)

    out = []
    for key, group in buckets.items():
        summary = _summarize(group)
        summary["key"] = key
        summary["group_by"] = group_by
        if group_by == "asset":
            summary["type"] = types.get(key)
        out.append(summary)
    return sorted(out, key=lambda s: s["total_hours"], reverse=True)


def asset_usage(db: Session, equipment_id: str, days: int = 90) -> dict:
    date_from, date_to = _window(days)
    rows = usage_rows(db, equipment_id=equipment_id, date_from=date_from, date_to=date_to)
    summary = _summarize(rows)
    summary["equipment_id"] = equipment_id
    summary["daily"] = [
        {
            "day": str(r.day),
            "engine_hours": r.engine_hours,
            "idle_hours": r.idle_hours,
            "utilization_pct": r.utilization_pct,
        }
        for r in rows
    ]
    # Date arithmetic differs across SQLite/Postgres -- do it in Python.
    today = datetime.now(timezone.utc).date()
    rentals = db.scalars(select(Rental).where(Rental.equipment_id == equipment_id))
    summary["total_rented_days"] = sum(
        ((r.actual_check_in_date or today) - r.check_out_date).days for r in rentals
    )
    return summary


def fleet_kpis(db: Session, days: int = 30) -> dict:
    date_from, date_to = _window(days)
    rows = usage_rows(db, date_from=date_from, date_to=date_to)
    summary = _summarize(rows)
    summary["window_days"] = days
    summary["assets_reporting"] = len({r.equipment_id for r in rows})
    return summary

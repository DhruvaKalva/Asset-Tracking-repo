"""Seed data.

The seven assets from the problem statement keep their exact usage signature so
the demo anomalies are real detections, not hardcoded theatre:

  EQX1001  1.5 engine / 10 idle  -> 87% idle, excessive-idle rule
  EQX1002  0 engine / 11 idle, no site, no operator -> ghost asset
  EQX1003  7.5 / 0.5             -> healthy baseline
  EQX1004  2 / 9                 -> idle + pushed past its return date
  EQX1005  8 / 0                 -> best-in-fleet baseline
  EQX1006  3 / 6                 -> borderline
  EQX1007  0 engine / 12 idle, no site -> ghost asset

Everything else is generated history so the forecaster has something to chew on.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.domain import projections
from app.models import (
    Alert,
    AnomalyScore,
    AssetCurrentState,
    AssetEvent,
    Equipment,
    EventType,
    Forecast,
    Operator,
    Rental,
    RentalStatus,
    Site,
    TelemetryDaily,
)

random.seed(42)

SITES = [
    ("S001", "Chennai Metro Package 4", "TN", 13.0827, 80.2707),
    ("S002", "Sriperumbudur Industrial Park", "TN", 12.9675, 79.9430),
    ("S003", "Hosur Highway Widening", "TN", 12.7409, 77.8253),
    ("S004", "Ennore Port Expansion", "TN", 13.2333, 80.3167),
    ("S005", "Coimbatore Ring Road", "TN", 11.0168, 76.9558),
    ("S006", "Neyveli Lignite Block C", "TN", 11.6093, 79.4900),
]

OPERATORS = [
    ("OP101", "R. Anand", "Excavator Class A", "+91-98400-11101"),
    ("OP106", "S. Muthu", "Excavator Class A", "+91-98400-11106"),
    ("OP114", "K. Devi", "Grader Class B", "+91-98400-11114"),
    ("OP203", "M. Bala", "Dozer Class A", "+91-98400-11203"),
    ("OP301", "T. Fernandes", "Dozer Class A", "+91-98400-11301"),
    ("OP305", "A. Krishnan", "Crane Class A", "+91-98400-11305"),
    ("OP412", "P. Ravi", "Multi-class", "+91-98400-11412"),
]

# type -> (rate/hour, service interval hours)
TYPE_SPEC = {
    "Excavator": (1850.0, 500.0),
    "Bulldozer": (2200.0, 600.0),
    "Crane": (3100.0, 400.0),
    "Grader": (1400.0, 500.0),
    "Loader": (1250.0, 500.0),
}

MODELS = {
    "Excavator": "CAT 320",
    "Bulldozer": "CAT D6",
    "Crane": "CAT CC34B",
    "Grader": "CAT 120",
    "Loader": "CAT 950M",
}

# equipment_id, type, site, operator, engine_h/day, idle_h/day, days_out, days_until_due
SCENARIO = [
    ("EQX1001", "Excavator", "S003", "OP101", 1.5, 10.0, 15, 4),    # 87% idle
    ("EQX1002", "Crane", None, None, 0.0, 11.0, 20, 6),             # ghost asset
    ("EQX1003", "Bulldozer", "S002", "OP203", 7.5, 0.5, 25, 9),     # healthy
    ("EQX1004", "Excavator", "S004", "OP106", 2.0, 9.0, 10, -3),    # idle + overdue
    ("EQX1005", "Bulldozer", "S006", "OP301", 8.0, 0.0, 30, 12),    # best in fleet
    ("EQX1006", "Grader", "S001", "OP114", 3.0, 6.0, 18, 2),        # due soon
    ("EQX1007", "Excavator", None, None, 0.0, 12.0, 12, 5),         # ghost asset
]

EXTRA_FLEET = [
    ("EQX1008", "Excavator"),
    ("EQX1009", "Excavator"),
    ("EQX1010", "Bulldozer"),
    ("EQX1011", "Grader"),
    ("EQX1012", "Loader"),
    ("EQX1013", "Loader"),
    ("EQX1014", "Crane"),
    ("EQX1015", "Excavator"),
    ("EQX1016", "Bulldozer"),
    ("EQX1017", "Grader"),
    ("EQX1018", "Loader"),
    ("EQX1019", "Excavator"),
    ("EQX1020", "Crane"),
]

HISTORY_WEEKS = 40


def _today() -> date:
    return datetime.now(timezone.utc).date()


def wipe(db: Session) -> None:
    for model in (
        AnomalyScore,
        Forecast,
        Alert,
        AssetEvent,
        TelemetryDaily,
        AssetCurrentState,
        Rental,
        Equipment,
        Operator,
        Site,
    ):
        db.execute(delete(model))
    db.commit()


def _make_equipment(db: Session) -> None:
    for eid, etype in [(s[0], s[1]) for s in SCENARIO] + EXTRA_FLEET:
        rate, interval = TYPE_SPEC[etype]
        lifetime = round(random.uniform(300, 2400), 1)
        db.add(
            Equipment(
                equipment_id=eid,
                type=etype,
                model=MODELS[etype],
                qr_payload=f"CAT-QR-{eid}",
                rfid_tag=f"RFID-{eid[-4:]}-{random.randint(1000, 9999)}",
                rental_rate_per_hour=rate,
                lifetime_engine_hours=lifetime,
                hours_at_last_service=round(max(lifetime - random.uniform(50, 520), 0), 1),
                service_interval_hours=interval,
            )
        )
    db.flush()


def _telemetry(
    db: Session,
    equipment_id: str,
    site_id: str | None,
    start: date,
    days: int,
    engine_per_day: float,
    idle_per_day: float,
    site_coords: dict,
    cache: dict[tuple[str, date], TelemetryDaily] | None = None,
) -> None:
    """Writes day buckets. `cache` keeps (asset, day) unique across overlapping rentals."""
    cache = cache if cache is not None else {}
    lat, lng = site_coords.get(site_id, (None, None))
    today = _today()

    for offset in range(days):
        day = start + timedelta(days=offset)
        if day > today:
            break
        jitter = random.uniform(0.85, 1.15)
        engine = round(engine_per_day * jitter, 2)
        idle = round(idle_per_day * random.uniform(0.9, 1.1), 2)

        row = cache.get((equipment_id, day))
        if row is not None:
            row.engine_hours = round(row.engine_hours + engine, 2)
            row.idle_hours = round(row.idle_hours + idle, 2)
            continue

        row = TelemetryDaily(
            equipment_id=equipment_id,
            day=day,
            engine_hours=engine,
            idle_hours=idle,
            fuel_litres=round(engine * random.uniform(11, 16), 1),
            site_id=site_id,
            lat=lat + random.uniform(-0.01, 0.01) if lat else None,
            lng=lng + random.uniform(-0.01, 0.01) if lng else None,
        )
        cache[(equipment_id, day)] = row
        db.add(row)
        # End-of-shift stamp, but never in the future -- today's bucket would
        # otherwise show up on the timeline hours ahead of now.
        stamp = min(
            datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
            + timedelta(hours=18),
            datetime.now(timezone.utc),
        )
        db.add(
            AssetEvent(
                equipment_id=equipment_id,
                event_type=EventType.TELEMETRY_TICK.value,
                payload={"engine_hours": engine, "idle_hours": idle, "day": str(day)},
                source="telemetry",
                occurred_at=stamp,
            )
        )


def _open_rentals(db: Session, site_coords: dict, cache: dict) -> None:
    today = _today()
    for eid, _etype, site, operator, engine, idle, days_out, days_due in SCENARIO:
        checkout = today - timedelta(days=days_out)
        expected = today + timedelta(days=days_due)
        status = RentalStatus.OVERDUE.value if days_due < 0 else RentalStatus.ACTIVE.value

        db.add(
            Rental(
                equipment_id=eid,
                site_id=site,
                operator_id=operator,
                check_out_date=checkout,
                expected_check_in_date=expected,
                status=status,
                checkout_notes="Seeded from problem-statement sample data",
            )
        )
        db.add(
            AssetEvent(
                equipment_id=eid,
                event_type=EventType.CHECK_OUT.value,
                payload={
                    "site_id": site,
                    "operator_id": operator,
                    "expected_check_in_date": str(expected),
                },
                source="qr",
                actor="seed",
                occurred_at=datetime.combine(checkout, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                ),
            )
        )
        _telemetry(db, eid, site, checkout, days_out + 1, engine, idle, site_coords, cache)
    db.flush()


def _history(db: Session, site_coords: dict, cache: dict) -> None:
    """Closed rentals across the last 40 weeks -- the forecaster's training data."""
    today = _today()
    extra_ids = [e[0] for e in EXTRA_FLEET]
    types = {e[0]: e[1] for e in EXTRA_FLEET}
    # An asset can only be on one rental at a time -- track when each frees up.
    busy_until: dict[str, date] = {}

    for week in range(HISTORY_WEEKS, 0, -1):
        week_start = today - timedelta(weeks=week)
        # Excavator demand at S003 trends upward; everything else is noisy-flat.
        trend = 1.0 + (HISTORY_WEEKS - week) / HISTORY_WEEKS * 0.8

        for site_id, *_ in SITES:
            for etype in TYPE_SPEC:
                base = {"Excavator": 1.6, "Bulldozer": 1.1, "Crane": 0.5, "Grader": 0.8, "Loader": 0.9}[etype]
                if site_id == "S003" and etype == "Excavator":
                    base *= trend
                count = max(0, int(random.gauss(base, 0.7)))

                for _ in range(count):
                    checkout = week_start + timedelta(days=random.randint(0, 4))
                    duration = random.randint(4, 16)
                    checkin = checkout + timedelta(days=duration)
                    if checkin >= today:
                        continue

                    candidates = [
                        e
                        for e in extra_ids
                        if types[e] == etype and busy_until.get(e, date.min) < checkout
                    ]
                    if not candidates:
                        continue
                    eid = random.choice(candidates)
                    busy_until[eid] = checkin

                    db.add(
                        Rental(
                            equipment_id=eid,
                            site_id=site_id,
                            operator_id=random.choice(OPERATORS)[0],
                            check_out_date=checkout,
                            expected_check_in_date=checkin,
                            actual_check_in_date=checkin,
                            status=RentalStatus.RETURNED.value,
                        )
                    )
                    # Only keep recent telemetry -- older rentals just feed demand counts.
                    if (today - checkout).days <= 60:
                        _telemetry(
                            db,
                            eid,
                            site_id,
                            checkout,
                            min(duration, 20),
                            random.uniform(4.5, 8.5),
                            random.uniform(0.5, 3.0),
                            site_coords,
                            cache,
                        )
    db.flush()


def _extra_open_rentals(db: Session, site_coords: dict, cache: dict, count: int = 6) -> None:
    """Puts part of the wider fleet on rent so the free pool is realistic.

    Without this every forecast shows surplus and the pre-positioning advice
    never has anything to say.
    """
    today = _today()
    on_rent = {s[0] for s in SCENARIO}
    pool = [e for e in EXTRA_FLEET if e[0] not in on_rent]
    random.shuffle(pool)

    for eid, etype in pool[:count]:
        site_id = random.choice(SITES)[0]
        days_out = random.randint(3, 14)
        checkout = today - timedelta(days=days_out)
        expected = today + timedelta(days=random.randint(2, 18))
        engine = random.uniform(4.5, 8.0)
        idle = random.uniform(0.4, 2.5)

        db.add(
            Rental(
                equipment_id=eid,
                site_id=site_id,
                operator_id=random.choice(OPERATORS)[0],
                check_out_date=checkout,
                expected_check_in_date=expected,
                status=RentalStatus.ACTIVE.value,
            )
        )
        db.add(
            AssetEvent(
                equipment_id=eid,
                event_type=EventType.CHECK_OUT.value,
                payload={"site_id": site_id, "expected_check_in_date": str(expected)},
                source="rfid",
                actor="seed",
                occurred_at=datetime.combine(checkout, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                ),
            )
        )
        _telemetry(db, eid, site_id, checkout, days_out + 1, engine, idle, site_coords, cache)
    db.flush()


# The grader that walked off site: a 14 km move with no transfer record. Gives
# the map, the trail endpoint and the geofence rule something real to show.
GEOFENCE_DEMO_ASSET = "EQX1006"
GEOFENCE_DEMO_SITE = "S001"


def _geofence_demo(db: Session) -> None:
    site = db.get(Site, GEOFENCE_DEMO_SITE)
    if site is None or site.lat is None:
        return

    now = datetime.now(timezone.utc)
    end_lat, end_lng = site.lat + 0.12, site.lng + 0.05  # ~14 km out

    # Six hourly pings walking away from the site, so the trail is a path.
    steps = 6
    for i in range(steps + 1):
        frac = i / steps
        lat = site.lat + (end_lat - site.lat) * frac
        lng = site.lng + (end_lng - site.lng) * frac
        db.add(
            AssetEvent(
                equipment_id=GEOFENCE_DEMO_ASSET,
                event_type=EventType.LOCATION_PING.value,
                payload={"lat": round(lat, 6), "lng": round(lng, 6)},
                source="telemetry",
                occurred_at=now - timedelta(hours=steps - i),
            )
        )

    latest = db.scalar(
        select(TelemetryDaily)
        .where(TelemetryDaily.equipment_id == GEOFENCE_DEMO_ASSET)
        .order_by(TelemetryDaily.day.desc())
        .limit(1)
    )
    if latest is not None:
        latest.lat, latest.lng = round(end_lat, 6), round(end_lng, 6)

    state = projections.get_or_create_state(db, GEOFENCE_DEMO_ASSET)
    state.lat, state.lng = round(end_lat, 6), round(end_lng, 6)
    db.flush()


def run(reset: bool = True) -> dict:
    init_db()
    db = SessionLocal()
    try:
        if reset:
            wipe(db)
        elif db.scalar(select(Equipment).limit(1)) is not None:
            return {"skipped": True, "reason": "database already seeded"}

        for site_id, name, region, lat, lng in SITES:
            db.add(Site(site_id=site_id, name=name, region=region, lat=lat, lng=lng))
        for oid, name, cert, phone in OPERATORS:
            db.add(Operator(operator_id=oid, name=name, certification=cert, phone=phone))
        db.flush()

        site_coords = {s[0]: (s[3], s[4]) for s in SITES}
        _make_equipment(db)
        telemetry_cache: dict = {}
        _open_rentals(db, site_coords, telemetry_cache)
        _history(db, site_coords, telemetry_cache)
        _extra_open_rentals(db, site_coords, telemetry_cache)
        db.commit()

        # Assets are "seen" now so the demo does not open with false stale-ping alerts.
        now = datetime.now(timezone.utc)
        for eid in db.scalars(select(Equipment.equipment_id)):
            projections.mark_seen(db, eid, now)
        db.commit()

        _geofence_demo(db)
        db.commit()

        count = projections.rebuild_all(db)

        return {
            "seeded": True,
            "sites": len(SITES),
            "operators": len(OPERATORS),
            "equipment": count,
            "rentals": db.scalar(select(func.count(Rental.rental_id))) or 0,
            "telemetry_days": db.scalar(select(func.count(TelemetryDaily.day))) or 0,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())

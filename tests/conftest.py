"""Test fixtures. Each test module gets its own throwaway SQLite file."""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest

# Point the app at a temp database before anything imports app.config.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="srts-test-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SIMULATOR_ENABLED"] = "false"

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    Equipment,
    Operator,
    Rental,
    RentalStatus,
    Site,
    TelemetryDaily,
)


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def today() -> date:
    return datetime.now(timezone.utc).date()


@pytest.fixture()
def fleet(db, today):
    """Two sites, two operators, and three assets with distinct usage signatures."""
    db.add_all(
        [
            Site(site_id="S001", name="Site One", lat=13.0, lng=80.0),
            Site(site_id="S002", name="Site Two", lat=12.9, lng=79.9),
            Operator(operator_id="OP101", name="R. Anand"),
            Operator(operator_id="OP203", name="M. Bala"),
        ]
    )
    specs = [
        ("EQX1001", "Excavator", 1850.0),  # will idle
        ("EQX1003", "Bulldozer", 2200.0),  # healthy
        ("EQX1009", "Excavator", 1850.0),  # free
    ]
    for eid, etype, rate in specs:
        db.add(
            Equipment(
                equipment_id=eid,
                type=etype,
                model="CAT test",
                qr_payload=f"CAT-QR-{eid}",
                rfid_tag=f"RFID-{eid}",
                rental_rate_per_hour=rate,
                lifetime_engine_hours=480.0,
                hours_at_last_service=0.0,
                service_interval_hours=500.0,
            )
        )
    db.commit()
    return db


def add_rental(
    db,
    equipment_id: str,
    site_id: str | None,
    operator_id: str | None,
    days_out: int,
    days_until_due: int,
    status: str = RentalStatus.ACTIVE.value,
) -> Rental:
    today = datetime.now(timezone.utc).date()
    rental = Rental(
        equipment_id=equipment_id,
        site_id=site_id,
        operator_id=operator_id,
        check_out_date=today - timedelta(days=days_out),
        expected_check_in_date=today + timedelta(days=days_until_due),
        status=status,
    )
    db.add(rental)
    db.commit()
    return rental


def add_usage(db, equipment_id: str, site_id: str | None, days: int, engine: float, idle: float):
    today = datetime.now(timezone.utc).date()
    for offset in range(days):
        db.add(
            TelemetryDaily(
                equipment_id=equipment_id,
                day=today - timedelta(days=offset),
                engine_hours=engine,
                idle_hours=idle,
                fuel_litres=engine * 12,
                site_id=site_id,
            )
        )
    db.commit()

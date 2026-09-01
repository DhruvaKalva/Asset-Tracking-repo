"""ORM models.

Design note: AssetEvent is the append-only source of truth. AssetCurrentState
and the aggregate tables are projections -- they can be dropped and rebuilt
from the event log at any time (see domain/projections.py::rebuild_all).
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres, plain JSON on SQLite -- same Python API either way.
JSONType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RentalStatus(str, enum.Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"


class AssetStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    IN_USE = "IN_USE"
    IDLE = "IDLE"
    OVERDUE = "OVERDUE"
    UNACCOUNTED = "UNACCOUNTED"
    MAINTENANCE = "MAINTENANCE"


class Mobility(str, enum.Enum):
    """Does this asset travel, or is it installed somewhere?

    MOVABLE is mobile plant -- excavators, dozers -- which gets checked out to a
    site, tracked, and geofenced. FIXED is stationary plant -- a tower crane, a
    generator, a batching plant -- which is installed at one site and stays
    there. Fixed assets are never rented out, so rental-shaped rules (overdue,
    geofence breach) do not apply to them.
    """

    MOVABLE = "MOVABLE"
    FIXED = "FIXED"


class EventType(str, enum.Enum):
    CHECK_OUT = "CHECK_OUT"
    CHECK_IN = "CHECK_IN"
    LOCATION_PING = "LOCATION_PING"
    TELEMETRY_TICK = "TELEMETRY_TICK"
    OPERATOR_ASSIGNED = "OPERATOR_ASSIGNED"
    ALERT_RAISED = "ALERT_RAISED"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    MAINTENANCE_LOGGED = "MAINTENANCE_LOGGED"


class Severity(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = {"INFO": 0, "WARN": 1, "HIGH": 2, "CRITICAL": 3}


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(80))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    # Assets found beyond this radius are off-site -- see ml/anomaly geofence rule.
    radius_km: Mapped[float] = mapped_column(Float, default=5.0)


class Operator(Base):
    __tablename__ = "operators"

    operator_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    certification: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(32))


class Equipment(Base):
    __tablename__ = "equipment"

    equipment_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str | None] = mapped_column(String(80))
    qr_payload: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rfid_tag: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    rental_rate_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
    lifetime_engine_hours: Mapped[float] = mapped_column(Float, default=0.0)
    hours_at_last_service: Mapped[float] = mapped_column(Float, default=0.0)
    service_interval_hours: Mapped[float] = mapped_column(Float, default=500.0)

    # MOVABLE by default so every pre-existing row keeps its current behaviour.
    mobility: Mapped[str] = mapped_column(String(8), default=Mobility.MOVABLE.value, index=True)
    # Where a FIXED asset is installed. Optional for MOVABLE plant, where it is
    # only the home yard and the rental decides the real site.
    home_site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)

    state: Mapped["AssetCurrentState"] = relationship(
        back_populates="equipment", uselist=False
    )


class Rental(Base):
    __tablename__ = "rentals"

    rental_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(
        ForeignKey("equipment.equipment_id"), index=True
    )
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"), index=True)
    operator_id: Mapped[str | None] = mapped_column(ForeignKey("operators.operator_id"))
    check_out_date: Mapped[date] = mapped_column(Date, index=True)
    expected_check_in_date: Mapped[date] = mapped_column(Date, index=True)
    actual_check_in_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    checkout_notes: Mapped[str | None] = mapped_column(Text)
    checkin_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_rentals_open", "equipment_id", "status"),)


class AssetEvent(Base):
    """Append-only. Never UPDATEd, never DELETEd. The audit trail is the product."""

    __tablename__ = "asset_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(String(24), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    source: Mapped[str] = mapped_column(String(16), default="system")
    actor: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)

    __table_args__ = (Index("ix_events_asset_time", "equipment_id", "occurred_at"),)


class TelemetryDaily(Base):
    """Partition by month on Postgres -- see db/partitions.sql."""

    __tablename__ = "telemetry_daily"

    equipment_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    engine_hours: Mapped[float] = mapped_column(Float, default=0.0)
    idle_hours: Mapped[float] = mapped_column(Float, default=0.0)
    fuel_litres: Mapped[float] = mapped_column(Float, default=0.0)
    site_id: Mapped[str | None] = mapped_column(String(16), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)

    @property
    def total_hours(self) -> float:
        return self.engine_hours + self.idle_hours

    @property
    def utilization_pct(self) -> float:
        t = self.total_hours
        return round(self.engine_hours / t * 100, 1) if t else 0.0


class AssetCurrentState(Base):
    __tablename__ = "asset_current_state"

    equipment_id: Mapped[str] = mapped_column(
        ForeignKey("equipment.equipment_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), default="AVAILABLE", index=True)
    site_id: Mapped[str | None] = mapped_column(String(16), index=True)
    operator_id: Mapped[str | None] = mapped_column(String(16))
    rental_id: Mapped[int | None] = mapped_column(Integer)
    expected_check_in_date: Mapped[date | None] = mapped_column(Date)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    engine_hours_today: Mapped[float] = mapped_column(Float, default=0.0)
    idle_hours_today: Mapped[float] = mapped_column(Float, default=0.0)
    utilization_pct: Mapped[float] = mapped_column(Float, default=0.0)
    health_flags: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    equipment: Mapped["Equipment"] = relationship(back_populates="state")


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(String(24), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(12), index=True)
    reason_text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)

    __table_args__ = (Index("ix_alerts_open", "dedupe_key", "resolved_at"),)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String(16), index=True)
    equipment_type: Mapped[str] = mapped_column(String(40), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    predicted_demand: Mapped[float] = mapped_column(Float)
    lower_ci: Mapped[float] = mapped_column(Float)
    upper_ci: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(48))
    driver_text: Mapped[str | None] = mapped_column(Text)
    mape: Mapped[float | None] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("site_id", "equipment_type", "week_start", name="uq_forecast_slot"),
    )


class AnomalyScore(Base):
    __tablename__ = "anomaly_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(String(24), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    rule_severity: Mapped[str] = mapped_column(String(12))
    ml_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_severity: Mapped[str] = mapped_column(String(12), index=True)
    reasons: Mapped[dict] = mapped_column(JSONType, default=dict)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("equipment_id", "day", name="uq_anomaly_slot"),)

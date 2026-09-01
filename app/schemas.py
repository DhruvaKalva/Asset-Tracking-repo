"""Request/response contracts. Keep the wire format stable and boring."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Reference
# --------------------------------------------------------------------------
class SiteOut(ORMModel):
    site_id: str
    name: str
    region: str | None = None
    lat: float | None = None
    lng: float | None = None
    radius_km: float = 5.0


class OperatorOut(ORMModel):
    operator_id: str
    name: str
    certification: str | None = None
    phone: str | None = None


class EquipmentOut(ORMModel):
    equipment_id: str
    type: str
    model: str | None = None
    qr_payload: str
    rfid_tag: str | None = None
    rental_rate_per_hour: float
    lifetime_engine_hours: float
    mobility: str = "MOVABLE"
    home_site_id: str | None = None
    service_interval_hours: float = 500.0


# --------------------------------------------------------------------------
# Assets / dashboard
# --------------------------------------------------------------------------
class AssetOut(BaseModel):
    equipment_id: str
    type: str
    model: str | None = None
    status: str
    site_id: str | None = None
    site_name: str | None = None
    operator_id: str | None = None
    operator_name: str | None = None
    rental_id: int | None = None
    check_out_date: date | None = None
    expected_check_in_date: date | None = None
    days_until_due: int | None = None
    last_seen_at: datetime | None = None
    lat: float | None = None
    lng: float | None = None
    engine_hours_today: float = 0.0
    idle_hours_today: float = 0.0
    utilization_pct: float = 0.0
    health_flags: dict = Field(default_factory=dict)
    open_alerts: int = 0
    rental_rate_per_hour: float = 0.0
    mobility: str = "MOVABLE"
    home_site_id: str | None = None


class EventOut(ORMModel):
    event_id: int
    equipment_id: str
    event_type: str
    payload: dict
    source: str
    actor: str | None = None
    occurred_at: datetime


class AssetDetail(BaseModel):
    asset: AssetOut
    usage: dict
    timeline: list[EventOut]
    alerts: list["AlertOut"]
    maintenance: dict | None = None


# --------------------------------------------------------------------------
# Check-in / check-out
# --------------------------------------------------------------------------
class CheckOutIn(BaseModel):
    scan_payload: str = Field(..., description="QR payload, RFID tag, or equipment_id")
    site_id: str
    operator_id: str | None = None
    expected_check_in_date: date | None = None
    actor: str | None = None
    notes: str | None = None
    idempotency_key: str | None = Field(
        None, description="Set by the offline PWA queue so retries cannot double-book"
    )


class CheckInIn(BaseModel):
    scan_payload: str
    actor: str | None = None
    notes: str | None = None
    idempotency_key: str | None = None


class AssignOperatorIn(BaseModel):
    operator_id: str
    actor: str | None = None


class RentalOut(ORMModel):
    rental_id: int
    equipment_id: str
    site_id: str | None = None
    operator_id: str | None = None
    check_out_date: date
    expected_check_in_date: date
    actual_check_in_date: date | None = None
    status: str


# --------------------------------------------------------------------------
# Telemetry
# --------------------------------------------------------------------------
class TelemetryTickIn(BaseModel):
    equipment_id: str
    engine_hours: float = 0.0
    idle_hours: float = 0.0
    fuel_litres: float = 0.0
    lat: float | None = None
    lng: float | None = None
    occurred_at: datetime | None = None
    idempotency_key: str | None = None


class TelemetryBatchIn(BaseModel):
    ticks: list[TelemetryTickIn]


class LocationIn(BaseModel):
    equipment_id: str
    lat: float
    lng: float


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
class AlertOut(ORMModel):
    alert_id: int
    equipment_id: str
    kind: str
    severity: str
    reason_text: str
    evidence: dict
    raised_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None


# --------------------------------------------------------------------------
# Intelligence
# --------------------------------------------------------------------------
class ForecastOut(ORMModel):
    site_id: str
    equipment_type: str
    week_start: date
    predicted_demand: float
    lower_ci: float
    upper_ci: float
    model_version: str
    driver_text: str | None = None
    mape: float | None = None
    generated_at: datetime


class AnomalyOut(ORMModel):
    equipment_id: str
    day: date
    rule_severity: str
    ml_score: float
    final_severity: str
    reasons: dict
    is_anomaly: bool
    detected_at: datetime


AssetDetail.model_rebuild()


# --------------------------------------------------------------------------
# Fleet registry (onboarding)
# --------------------------------------------------------------------------
class EquipmentCreate(BaseModel):
    type: str = Field(..., description="Excavator, Bulldozer, Crane, Grader, Loader, ...")
    model: str | None = None
    equipment_id: str | None = Field(None, description="Auto-assigned (EQX####) when omitted")
    rental_rate_per_hour: float = Field(0.0, ge=0)
    service_interval_hours: float = Field(500.0, gt=0)
    lifetime_engine_hours: float = Field(0.0, ge=0, description="Hours on the clock at intake")
    hours_at_last_service: float | None = Field(
        None, description="Defaults to lifetime hours so a used intake is not instantly overdue"
    )
    qr_payload: str | None = Field(None, description="Auto-minted as CAT-QR-<id> when omitted")
    rfid_tag: str | None = None
    mobility: Literal["MOVABLE", "FIXED"] = Field(
        "MOVABLE",
        description="MOVABLE = mobile plant, rented out and geofenced. FIXED = installed at one site.",
    )
    home_site_id: str | None = Field(
        None, description="Where a FIXED asset is installed. Required when mobility is FIXED."
    )
    actor: str | None = None


class EquipmentUpdate(BaseModel):
    type: str | None = None
    model: str | None = None
    rental_rate_per_hour: float | None = Field(None, ge=0)
    service_interval_hours: float | None = Field(None, gt=0)
    hours_at_last_service: float | None = Field(None, ge=0)
    rfid_tag: str | None = None
    mobility: Literal["MOVABLE", "FIXED"] | None = None
    home_site_id: str | None = None
    actor: str | None = None


class ServiceLogIn(BaseModel):
    notes: str | None = None
    actor: str | None = None


class SiteCreate(BaseModel):
    site_id: str
    name: str
    region: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    radius_km: float = Field(5.0, gt=0, description="Geofence boundary for this site")


class SiteUpdate(BaseModel):
    name: str | None = None
    region: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    radius_km: float | None = Field(None, gt=0)


class OperatorCreate(BaseModel):
    operator_id: str
    name: str
    certification: str | None = None
    phone: str | None = None


# --------------------------------------------------------------------------
# Tracking
# --------------------------------------------------------------------------
class TrackPoint(BaseModel):
    lat: float
    lng: float
    at: datetime
    source: str
    event_type: str

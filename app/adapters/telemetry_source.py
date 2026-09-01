"""Telemetry sources.

SimulatedSource drives the demo: each tick advances every on-rent asset by a
fraction of a day using that asset's own recent behaviour, so EQX1001 keeps
idling and EQX1005 keeps working. Swapping in MqttSource or a VisionLink poller
means implementing `poll()` -- the ingest path does not change.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import telemetry_service
from app.models import AssetCurrentState, Rental, RentalStatus, Site, TelemetryDaily

log = logging.getLogger(__name__)

ON_RENT = (RentalStatus.ACTIVE.value, RentalStatus.OVERDUE.value)


class TelemetrySource(Protocol):
    name: str

    def poll(self, db: Session) -> int: ...


class SimulatedSource:
    name = "simulator"

    def __init__(self, hours_per_tick: float | None = None) -> None:
        self.hours_per_tick = hours_per_tick or settings.simulator_hours_per_tick

    def _profile(self, db: Session, equipment_id: str) -> tuple[float, float]:
        """Recent engine/idle split for this asset, per hour of wall time."""
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=14)
        rows = list(
            db.scalars(
                select(TelemetryDaily).where(
                    TelemetryDaily.equipment_id == equipment_id, TelemetryDaily.day >= cutoff
                )
            )
        )
        if not rows:
            return 0.6, 0.2
        engine = sum(r.engine_hours for r in rows) / len(rows)
        idle = sum(r.idle_hours for r in rows) / len(rows)
        # normalise a day's worth of behaviour down to one simulated hour
        denom = max(engine + idle, 1e-6)
        return engine / denom, idle / denom

    def poll(self, db: Session) -> int:
        rentals = list(db.scalars(select(Rental).where(Rental.status.in_(ON_RENT))))
        if not rentals:
            return 0

        sites = {s.site_id: s for s in db.scalars(select(Site))}
        now = datetime.now(timezone.utc)
        count = 0

        for rental in rentals:
            engine_share, idle_share = self._profile(db, rental.equipment_id)
            span = self.hours_per_tick * random.uniform(0.85, 1.15)
            engine_h = round(engine_share * span, 3)
            idle_h = round(idle_share * span, 3)

            lat = lng = None
            site = sites.get(rental.site_id) if rental.site_id else None
            if site and site.lat is not None:
                # small random walk around the site so the map looks alive
                state = db.get(AssetCurrentState, rental.equipment_id)
                base_lat = state.lat if state and state.lat else site.lat
                base_lng = state.lng if state and state.lng else site.lng
                lat = round(base_lat + random.uniform(-0.002, 0.002), 6)
                lng = round(base_lng + random.uniform(-0.002, 0.002), 6)

            telemetry_service.ingest_tick(
                db,
                equipment_id=rental.equipment_id,
                engine_hours=engine_h,
                idle_hours=idle_h,
                fuel_litres=round(engine_h * random.uniform(11, 16), 2),
                lat=lat,
                lng=lng,
                occurred_at=now,
                source="simulator",
                commit=False,
            )
            count += 1

        db.commit()
        return count


class MqttSource:  # pragma: no cover - production placeholder
    """Real fleets publish to a broker; subscribe here and call ingest_batch."""

    name = "mqtt"

    def poll(self, db: Session) -> int:
        raise NotImplementedError("configure MQTT_BROKER_URL and implement subscribe()")


def get_source() -> TelemetrySource:
    return SimulatedSource()

"""Writes to the event log. Every state change in the system passes through here."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.bus import bus
from app.models import AssetEvent, EventType


def make_idempotency_key(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def record_event(
    db: Session,
    equipment_id: str,
    event_type: EventType | str,
    payload: dict | None = None,
    source: str = "system",
    actor: str | None = None,
    occurred_at: datetime | None = None,
    idempotency_key: str | None = None,
    publish: bool = True,
) -> AssetEvent | None:
    """Append one event. Returns None when the key was already ingested.

    Idempotency matters more than it looks: site connectivity is bad, the PWA
    retries queued scans, and a double-scan must not create a double booking.
    """
    etype = event_type.value if isinstance(event_type, EventType) else str(event_type)

    if idempotency_key:
        existing = db.scalar(
            select(AssetEvent).where(AssetEvent.idempotency_key == idempotency_key)
        )
        if existing:
            return None

    event = AssetEvent(
        equipment_id=equipment_id,
        event_type=etype,
        payload=payload or {},
        source=source,
        actor=actor,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        idempotency_key=idempotency_key,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:  # lost a race on the unique key
        db.rollback()
        return None

    if publish:
        bus.publish(
            "event",
            {
                "equipment_id": equipment_id,
                "event_type": etype,
                "payload": event.payload,
                "occurred_at": event.occurred_at,
            },
        )
    return event


def find_by_idempotency_key(db: Session, key: str) -> AssetEvent | None:
    return db.scalar(select(AssetEvent).where(AssetEvent.idempotency_key == key))


def timeline(db: Session, equipment_id: str, limit: int = 100) -> list[AssetEvent]:
    return list(
        db.scalars(
            select(AssetEvent)
            .where(AssetEvent.equipment_id == equipment_id)
            .order_by(AssetEvent.occurred_at.desc(), AssetEvent.event_id.desc())
            .limit(limit)
        )
    )

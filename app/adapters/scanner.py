"""Identity resolution: raw scan payload -> equipment_id.

The whole point of this file is that the API never knows whether the scan came
from a phone camera, an RFID gate, or a dispatcher typing an ID. Adding a real
RFID reader later means adding a class here, nothing else.
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Equipment


class ScanError(LookupError):
    pass


class ScannerAdapter(Protocol):
    source: str

    def resolve(self, db: Session, raw: str) -> str | None: ...


class QRScanner:
    """Payload printed on the asset sticker, e.g. CAT-QR-EQX1001."""

    source = "qr"

    def resolve(self, db: Session, raw: str) -> str | None:
        return db.scalar(select(Equipment.equipment_id).where(Equipment.qr_payload == raw))


class RFIDScanner:
    source = "rfid"

    def resolve(self, db: Session, raw: str) -> str | None:
        return db.scalar(select(Equipment.equipment_id).where(Equipment.rfid_tag == raw))


class ManualEntry:
    source = "manual"

    def resolve(self, db: Session, raw: str) -> str | None:
        return db.scalar(
            select(Equipment.equipment_id).where(Equipment.equipment_id == raw.upper())
        )


class CompositeScanner:
    """Tries each adapter in order. One endpoint handles every scan method."""

    source = "composite"

    def __init__(self, adapters: list[ScannerAdapter] | None = None) -> None:
        self.adapters = adapters or [QRScanner(), RFIDScanner(), ManualEntry()]

    def resolve_with_source(self, db: Session, raw: str) -> tuple[str, str]:
        raw = (raw or "").strip()
        if not raw:
            raise ScanError("empty scan payload")
        for adapter in self.adapters:
            found = adapter.resolve(db, raw)
            if found:
                return found, adapter.source
        raise ScanError(f"no equipment matches scan payload {raw!r}")

    def resolve(self, db: Session, raw: str) -> str:
        return self.resolve_with_source(db, raw)[0]


def get_scanner() -> CompositeScanner:
    return CompositeScanner()

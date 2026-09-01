"""Condition photos for check-out and check-in.

Rental disputes are the reason this exists: "it came back with a cracked screen"
is a claim, and a timestamped photo from each end of the hire is the evidence.
So a photo is stored against the *rental*, not just the asset -- the check-out
set and the check-in set of the same hire are the pair that gets compared.

Files land on disk under settings.media_root and are served as static content.
Only metadata goes in the database.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import projections
from app.domain.errors import Conflict, NotFound
from app.domain.events import record_event
from app.models import AssetPhoto, Equipment, EventType, PhotoKind, Rental

log = logging.getLogger(__name__)

# Raster only, and deliberately no SVG: an SVG is a script container, and these
# files are served back from our own origin.
ALLOWED = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

# The content-type header is client-supplied, so the real check is the file's
# own leading bytes.
MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


def sniff_type(blob: bytes) -> str | None:
    """Content type from the bytes themselves, or None if it is not an image."""
    for prefix, mime in MAGIC:
        if blob.startswith(prefix):
            return mime
    # WEBP is "RIFF" + 4 size bytes + "WEBP"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


def media_root() -> Path:
    root = Path(settings.media_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def photo_dir(equipment_id: str) -> Path:
    d = media_root() / "photos" / equipment_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def url_for(photo: AssetPhoto) -> str:
    return f"/media/photos/{photo.equipment_id}/{photo.stored_name}"


def to_dict(photo: AssetPhoto) -> dict:
    return {
        "photo_id": photo.photo_id,
        "equipment_id": photo.equipment_id,
        "rental_id": photo.rental_id,
        "kind": photo.kind,
        "url": url_for(photo),
        "original_name": photo.original_name,
        "content_type": photo.content_type,
        "size_bytes": photo.size_bytes,
        "caption": photo.caption,
        "actor": photo.actor,
        "taken_at": photo.taken_at,
    }


def _resolve_rental(db: Session, equipment_id: str, kind: str, rental_id: int | None) -> int | None:
    """Pick the rental leg these photos belong to.

    Explicit wins. Otherwise the open rental is the right answer for both ends:
    at check-out it was just created, and at check-in the caller photographs
    before completing the return. If the return already happened, fall back to
    the most recent rental so a late upload still lands on the right hire.
    """
    if rental_id is not None:
        rental = db.get(Rental, rental_id)
        if rental is None:
            raise NotFound(f"unknown rental {rental_id}")
        if rental.equipment_id != equipment_id:
            raise Conflict(f"rental {rental_id} does not belong to {equipment_id}")
        return rental_id

    open_rental = projections.open_rental(db, equipment_id)
    if open_rental is not None:
        return open_rental.rental_id

    latest = db.scalar(
        select(Rental)
        .where(Rental.equipment_id == equipment_id)
        .order_by(Rental.check_out_date.desc(), Rental.rental_id.desc())
        .limit(1)
    )
    return latest.rental_id if latest else None


def add_photo(
    db: Session,
    equipment_id: str,
    kind: str,
    blob: bytes,
    original_name: str | None = None,
    caption: str | None = None,
    actor: str | None = None,
    rental_id: int | None = None,
    commit: bool = True,
) -> AssetPhoto:
    equipment_id = equipment_id.upper().strip()
    if db.get(Equipment, equipment_id) is None:
        raise NotFound(f"unknown equipment {equipment_id}")

    kind = (kind or "").upper().strip()
    if kind not in {k.value for k in PhotoKind}:
        raise Conflict(f"kind must be CHECK_OUT or CHECK_IN, got {kind!r}")

    if not blob:
        raise Conflict("empty file")

    limit = int(settings.max_photo_mb * 1024 * 1024)
    if len(blob) > limit:
        raise Conflict(
            f"photo is {len(blob) / 1048576:.1f} MB; the limit is {settings.max_photo_mb:.0f} MB"
        )

    content_type = sniff_type(blob)
    if content_type is None:
        raise Conflict("file is not a JPEG, PNG or WebP image")

    rental_id = _resolve_rental(db, equipment_id, kind, rental_id)

    stored_name = f"{uuid.uuid4().hex}{ALLOWED[content_type]}"
    path = photo_dir(equipment_id) / stored_name
    path.write_bytes(blob)

    photo = AssetPhoto(
        equipment_id=equipment_id,
        rental_id=rental_id,
        kind=kind,
        stored_name=stored_name,
        original_name=(original_name or "")[:255] or None,
        content_type=content_type,
        size_bytes=len(blob),
        caption=(caption or "").strip() or None,
        actor=actor,
    )
    db.add(photo)
    db.flush()

    # The audit trail has to mention it, or "where is the proof" has no answer.
    record_event(
        db,
        equipment_id,
        EventType.PHOTO_ADDED,
        payload={
            "photo_id": photo.photo_id,
            "kind": kind,
            "rental_id": rental_id,
            "url": url_for(photo),
            "size_bytes": len(blob),
        },
        source="manual",
        actor=actor,
        publish=False,
    )

    if commit:
        db.commit()
    return photo


def list_photos(
    db: Session,
    equipment_id: str,
    kind: str | None = None,
    rental_id: int | None = None,
    limit: int = 200,
) -> list[dict]:
    stmt = select(AssetPhoto).where(AssetPhoto.equipment_id == equipment_id.upper())
    if kind:
        stmt = stmt.where(AssetPhoto.kind == kind.upper())
    if rental_id is not None:
        stmt = stmt.where(AssetPhoto.rental_id == rental_id)
    stmt = stmt.order_by(AssetPhoto.taken_at.desc(), AssetPhoto.photo_id.desc()).limit(limit)
    return [to_dict(p) for p in db.scalars(stmt)]


def photo_counts(db: Session, equipment_id: str) -> dict:
    rows = list_photos(db, equipment_id)
    return {
        "total": len(rows),
        "check_out": sum(1 for r in rows if r["kind"] == PhotoKind.CHECK_OUT.value),
        "check_in": sum(1 for r in rows if r["kind"] == PhotoKind.CHECK_IN.value),
    }

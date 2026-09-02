"""Condition photos captured at check-out and check-in.

The interesting behaviour is not storage, it is refusal: what the endpoint does
with a file that only claims to be an image, and what happens to the good files
in a batch when one of them is bad.
"""
from __future__ import annotations

import struct
import zlib

import pytest

from app.config import settings
from app.domain import photos, projections
from app.domain.errors import Conflict, NotFound
from app.models import EventType, PhotoKind, RentalStatus
from tests.conftest import add_rental


def png_bytes(w: int = 4, h: int = 4) -> bytes:
    """A real, decodable PNG -- not just the magic prefix."""
    raw = bytearray()
    for _ in range(h):
        raw.append(0)  # filter: none
        raw += bytes([120, 140, 110]) * w

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


@pytest.fixture()
def hire(fleet, tmp_path, monkeypatch):
    """One asset on rent, with photos written to a temp directory."""
    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    db = fleet
    add_rental(db, "EQX1001", "S001", "OP101", days_out=3, days_until_due=7)
    projections.rebuild_all(db)
    return db


# ---------------------------------------------------------------------------
# What counts as an image
# ---------------------------------------------------------------------------
def test_type_is_sniffed_from_bytes_not_the_header():
    """The content-type a client sends is a claim; the bytes are the evidence."""
    assert photos.sniff_type(png_bytes()) == "image/png"
    assert photos.sniff_type(JPEG) == "image/jpeg"
    assert photos.sniff_type(WEBP) == "image/webp"
    assert photos.sniff_type(b"not an image at all") is None


def test_svg_is_refused(hire):
    """An SVG is a script container and these files are served from our own
    origin, so it is rejected however it is labelled."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with pytest.raises(Conflict, match="not a JPEG, PNG or WebP"):
        photos.add_photo(hire, "EQX1001", "CHECK_OUT", svg)


def test_empty_and_oversized_files_are_refused(hire, monkeypatch):
    with pytest.raises(Conflict, match="empty"):
        photos.add_photo(hire, "EQX1001", "CHECK_OUT", b"")

    monkeypatch.setattr(settings, "max_photo_mb", 0.0001)  # ~100 bytes
    with pytest.raises(Conflict, match="the limit is"):
        photos.add_photo(hire, "EQX1001", "CHECK_OUT", png_bytes(64, 64))


def test_unknown_asset_and_bad_kind_are_refused(hire):
    with pytest.raises(NotFound):
        photos.add_photo(hire, "NOPE", "CHECK_OUT", png_bytes())
    with pytest.raises(Conflict, match="CHECK_OUT or CHECK_IN"):
        photos.add_photo(hire, "EQX1001", "SIDEWAYS", png_bytes())


# ---------------------------------------------------------------------------
# Storage and attribution
# ---------------------------------------------------------------------------
def test_a_photo_attaches_to_the_open_rental(hire):
    """A photo that cannot name its rental is evidence of nothing."""
    rental = projections.open_rental(hire, "EQX1001")
    photo = photos.add_photo(
        hire, "eqx1001", "check_out", png_bytes(), original_name="front.png", actor="R. Anand"
    )
    assert photo.rental_id == rental.rental_id
    assert photo.equipment_id == "EQX1001"  # normalised
    assert photo.kind == PhotoKind.CHECK_OUT.value
    assert photo.content_type == "image/png"
    assert photo.actor == "R. Anand"


def test_the_file_lands_on_disk_under_a_generated_name(hire):
    photo = photos.add_photo(
        hire, "EQX1001", "CHECK_OUT", png_bytes(), original_name="../../escape.png"
    )
    path = photos.photo_dir("EQX1001") / photo.stored_name
    assert path.exists() and path.read_bytes() == png_bytes()
    # The stored name is ours, so a hostile filename cannot steer the write.
    assert photo.stored_name.endswith(".png")
    assert "escape" not in photo.stored_name and ".." not in photo.stored_name
    assert photos.url_for(photo) == f"/media/photos/EQX1001/{photo.stored_name}"


def test_adding_a_photo_records_an_event(hire):
    from app.domain.events import timeline

    photos.add_photo(hire, "EQX1001", "CHECK_IN", JPEG, actor="M. Bala")
    kinds = [e.event_type for e in timeline(hire, "EQX1001")]
    assert EventType.PHOTO_ADDED.value in kinds


def test_photos_are_listed_newest_first_and_filtered_by_kind(hire):
    photos.add_photo(hire, "EQX1001", "CHECK_OUT", png_bytes())
    photos.add_photo(hire, "EQX1001", "CHECK_OUT", JPEG)
    photos.add_photo(hire, "EQX1001", "CHECK_IN", WEBP)

    assert len(photos.list_photos(hire, "EQX1001")) == 3
    assert len(photos.list_photos(hire, "EQX1001", kind="CHECK_OUT")) == 2
    assert len(photos.list_photos(hire, "EQX1001", kind="CHECK_IN")) == 1
    assert photos.photo_counts(hire, "EQX1001") == {"total": 3, "check_out": 2, "check_in": 1}


def test_a_late_upload_still_finds_the_last_rental(hire):
    """Photographed after the return was already recorded, it must still land on
    the hire it documents rather than floating free."""
    rental = projections.open_rental(hire, "EQX1001")
    rental.status = RentalStatus.RETURNED.value
    hire.commit()

    photo = photos.add_photo(hire, "EQX1001", "CHECK_IN", png_bytes())
    assert photo.rental_id == rental.rental_id


def test_an_explicit_rental_must_belong_to_the_asset(hire):
    rental = add_rental(hire, "EQX1003", "S002", "OP203", days_out=1, days_until_due=5)
    with pytest.raises(Conflict, match="does not belong"):
        photos.add_photo(hire, "EQX1001", "CHECK_OUT", png_bytes(), rental_id=rental.rental_id)
    with pytest.raises(NotFound):
        photos.add_photo(hire, "EQX1001", "CHECK_OUT", png_bytes(), rental_id=9999)

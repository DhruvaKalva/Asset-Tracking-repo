"""Condition photos captured at check-out and check-in.

Upload is multipart because that is what a camera capture and a file picker
both produce natively; nothing has to base64-encode an image to get it here.

Several files arrive in one request on purpose. A walkaround is four or five
shots of the same machine, and one request per shot would mean a partially
recorded handover if the third one failed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import photos
from app.domain.errors import Conflict
from app.schemas import PhotoOut, PhotoUploadResult

router = APIRouter(tags=["photos"])

MAX_FILES = 12


@router.get("/assets/{equipment_id}/photos", response_model=list[PhotoOut])
def list_asset_photos(
    equipment_id: str,
    kind: str | None = None,
    rental_id: int | None = None,
    db: Session = Depends(get_db),
):
    return photos.list_photos(db, equipment_id, kind=kind, rental_id=rental_id)


@router.post(
    "/assets/{equipment_id}/photos",
    response_model=PhotoUploadResult,
    status_code=201,
)
async def upload_asset_photos(
    equipment_id: str,
    files: list[UploadFile] = File(..., description="JPEG, PNG or WebP"),
    kind: str = Form(..., description="CHECK_OUT or CHECK_IN"),
    caption: str | None = Form(None),
    actor: str | None = Form(None),
    rental_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    if not files:
        raise Conflict("no files in the request")
    if len(files) > MAX_FILES:
        raise Conflict(f"{len(files)} files in one request; the limit is {MAX_FILES}")

    saved, rejected = [], []
    for upload in files:
        blob = await upload.read()
        try:
            # commit=False: the whole set lands together or not at all, so a
            # handover is never half-recorded.
            photo = photos.add_photo(
                db,
                equipment_id,
                kind,
                blob,
                original_name=upload.filename,
                caption=caption,
                actor=actor,
                rental_id=rental_id,
                commit=False,
            )
            saved.append(photos.to_dict(photo))
        except Conflict as exc:
            # One unreadable file should not lose the other four. The caller is
            # told which ones failed and why.
            rejected.append({"file": upload.filename or "(unnamed)", "reason": str(exc)})

    if not saved:
        db.rollback()
        raise Conflict(rejected[0]["reason"] if rejected else "nothing was saved")

    db.commit()
    return {"saved": saved, "rejected": rejected}

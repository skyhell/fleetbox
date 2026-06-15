"""Document & photo uploads attached to vehicles (and optionally records).

Files are stored on disk under ``settings.upload_path`` with an opaque random
name; the original filename and metadata live in the database. Uploads are
restricted to a small allowlist of image and PDF types and a per-file size cap.
Every access is checked against the requesting user's ownership of the vehicle.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import ALLOWED_UPLOAD_TYPES, settings
from app.database import get_db
from app.models import Attachment, ServiceRecord, User, Vehicle
from app.security import require_user

router = APIRouter(prefix="/vehicles/{vehicle_id}", tags=["attachments"])

# Read uploads in modest chunks so we can abort oversized files without first
# buffering the whole thing in memory.
_CHUNK = 64 * 1024


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.post("/attachments")
async def upload_attachment(
    vehicle_id: int,
    file: UploadFile = File(...),
    title: str = Form(""),
    service_record_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)

    extension = ALLOWED_UPLOAD_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type",
        )

    # Optional link to one of this vehicle's service records.
    record_id = service_record_id.strip()
    linked_record_id: int | None = None
    if record_id:
        record = db.get(ServiceRecord, int(record_id))
        if record is None or record.vehicle_id != vehicle.id:
            raise HTTPException(status_code=404, detail="Service record not found")
        linked_record_id = record.id

    stored_name = secrets.token_hex(16) + extension
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    target = settings.upload_path / stored_name

    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="File too large",
                    )
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    attachment = Attachment(
        vehicle_id=vehicle.id,
        service_record_id=linked_record_id,
        title=title.strip() or None,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        content_type=file.content_type,
        size=size,
    )
    # The first uploaded image becomes the vehicle's title image automatically.
    if attachment.is_image and vehicle.primary_image is None:
        attachment.is_primary = True
    db.add(attachment)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.get("/attachments/{attachment_id}")
def download_attachment(
    vehicle_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Attachment not found")

    path = settings.upload_path / attachment.stored_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing")

    # Images render inline; everything else (PDFs) is offered as a download.
    disposition = "inline" if attachment.is_image else "attachment"
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type=disposition,
    )


@router.post("/attachments/{attachment_id}/primary")
def set_primary_attachment(
    vehicle_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.vehicle_id != vehicle.id or not attachment.is_image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Toggle: clicking the current title image clears it; otherwise this image
    # becomes the title image and any previous one is unset.
    make_primary = not attachment.is_primary
    for other in vehicle.attachments:
        other.is_primary = False
    attachment.is_primary = make_primary
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/attachments/{attachment_id}/delete")
def delete_attachment(
    vehicle_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Attachment not found")

    (settings.upload_path / attachment.stored_name).unlink(missing_ok=True)
    db.delete(attachment)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)

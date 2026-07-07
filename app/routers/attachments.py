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

# Leading file signatures ("magic bytes") per allowed content type. Checked in
# addition to the client-supplied content type, so a mislabelled file (e.g.
# HTML posing as an image) is rejected before it is stored.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
}


def signature_ok(content_type: str, head: bytes) -> bool:
    """True when ``head`` (the file's first bytes) matches ``content_type``."""
    if content_type == "image/webp":  # RIFF container: RIFF....WEBP
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    signatures = _SIGNATURES.get(content_type)
    return signatures is not None and head.startswith(signatures)


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


async def save_attachment(
    db: Session,
    vehicle: Vehicle,
    file: UploadFile,
    *,
    title: str | None = None,
    service_record_id: int | None = None,
    as_title_image: bool = False,
) -> Attachment:
    """Validate, store on disk and register an uploaded file for a vehicle.

    Raises 415 for disallowed content types and 413 when the size cap is
    exceeded (any partial file is removed from disk). With ``as_title_image``
    the upload becomes the vehicle's photo, replacing (deleting) the previous
    one — the vehicle photo is managed exclusively through the vehicle form.
    Regular uploads never touch the title image. The caller commits.
    """
    extension = ALLOWED_UPLOAD_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type",
        )

    stored_name = secrets.token_hex(16) + extension
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    target = settings.upload_path / stored_name

    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                if size == 0 and not signature_ok(file.content_type or "", chunk):
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="File content does not match its declared type",
                    )
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="File too large",
                    )
                out.write(chunk)
        if size == 0:  # empty upload can't match any signature
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Empty file",
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise

    attachment = Attachment(
        vehicle_id=vehicle.id,
        service_record_id=service_record_id,
        title=(title or "").strip() or None,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        content_type=file.content_type,
        size=size,
    )
    if as_title_image and attachment.is_image:
        # Replace the previous vehicle photo (row and file).
        for old in [a for a in vehicle.attachments if a.is_primary]:
            (settings.upload_path / old.stored_name).unlink(missing_ok=True)
            db.delete(old)
        attachment.is_primary = True
    db.add(attachment)
    return attachment


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

    # Optional link to one of this vehicle's service records.
    record_id = service_record_id.strip()
    linked_record_id: int | None = None
    if record_id:
        record = db.get(ServiceRecord, int(record_id))
        if record is None or record.vehicle_id != vehicle.id:
            raise HTTPException(status_code=404, detail="Service record not found")
        linked_record_id = record.id

    await save_attachment(
        db, vehicle, file, title=title, service_record_id=linked_record_id
    )
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
    response = FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.filename,
        content_disposition_type=disposition,
    )
    # Serve user-uploaded content in an origin-less sandbox: even if a crafted
    # file slipped through validation, it cannot run scripts or reach the app's
    # origin when opened directly.
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


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

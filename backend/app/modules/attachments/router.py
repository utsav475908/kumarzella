import hashlib
import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import NotFound, ValidationFailed
from app.core.storage import get_storage
from app.modules.attachments.models import Attachment
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.trades.schemas import AttachmentOut
from app.modules.trades.service import get_owned_trade

router = APIRouter(tags=["attachments"])

# Content type is decided by magic bytes, never by the client-supplied header or extension.
SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
]


def sniff(data: bytes) -> str | None:
    for sig, ct in SIGNATURES:
        if data.startswith(sig):
            return ct
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip() or "file"
    return name[:200]


@router.post("/trades/{trade_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    trade_id: UUID, file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    t = get_owned_trade(db, user.id, trade_id)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large", code="file_too_large")
    if not data:
        raise ValidationFailed("File is empty", code="empty_file")
    ct = sniff(data)
    if ct is None:
        raise ValidationFailed(
            "Only PNG, JPEG, GIF, WebP images and PDF files are allowed", code="unsupported_file_type"
        )
    att = Attachment(
        user_id=user.id, trade_id=t.id, storage_key="", filename=safe_name(file.filename or "file"),
        content_type=ct, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
    )  # fmt: skip
    db.add(att)
    db.flush()
    att.storage_key = f"attachments/{user.id}/{att.id}"
    get_storage().put(att.storage_key, data, ct)
    audit.record(db, user_id=user.id, action="trade.attachment_added", entity_type="trade", entity_id=t.id)
    db.commit()
    return att


def _att(db: Session, user: User, att_id: UUID) -> Attachment:
    a = db.get(Attachment, att_id)
    if a is None or a.user_id != user.id:
        raise NotFound("Attachment not found")
    return a


@router.get("/attachments/{attachment_id}/content")
def download(attachment_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _att(db, user, attachment_id)
    data = get_storage().get(a.storage_key)
    disposition = "inline" if a.content_type.startswith("image/") else "attachment"
    return Response(
        content=data,
        media_type=a.content_type,
        headers={
            "content-disposition": f'{disposition}; filename="{a.filename}"',
            "cache-control": "private, max-age=300",
            "content-security-policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = _att(db, user, attachment_id)
    key = a.storage_key
    kind = "trade" if a.trade_id else "playbook"
    audit.record(db, user_id=user.id, action=f"{kind}.attachment_deleted", entity_type=kind,
                 entity_id=a.trade_id or a.playbook_id)  # fmt: skip
    db.delete(a)
    db.commit()
    get_storage().delete(key)
    return Response(status_code=204)

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import get_current_user
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.schemas import ApiModel, decimal_safe_json
from app.core.storage import get_storage
from app.modules.analytics import reports
from app.modules.attachments.models import Attachment
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.playbooks import service
from app.modules.playbooks.models import Playbook, PlaybookVersion
from app.modules.trades.filters import TradeFilters, trade_filters

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


class ChecklistItem(ApiModel):
    id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,32}$")
    text: str = Field(min_length=1, max_length=500)


class RulesIn(ApiModel):
    instruments: list[str] = Field(default_factory=list, max_length=100)
    timeframe: str | None = Field(None, max_length=32)
    permitted_sessions: list[Literal["regular", "extended"]] = Field(default_factory=list)
    entry_hour_start: int | None = Field(None, ge=0, le=23)
    entry_hour_end: int | None = Field(None, ge=1, le=24)
    entry_rules: str | None = Field(None, max_length=20000)
    exit_rules: str | None = Field(None, max_length=20000)
    stop_rules: str | None = Field(None, max_length=20000)
    target_rules: str | None = Field(None, max_length=20000)
    sizing_rules: str | None = Field(None, max_length=20000)
    invalidation: str | None = Field(None, max_length=20000)
    valid_examples: str | None = Field(None, max_length=20000)
    invalid_examples: str | None = Field(None, max_length=20000)
    require_stop: bool = False
    max_risk_per_trade: Decimal | None = Field(None, gt=0)
    min_reward_risk: Decimal | None = Field(None, gt=0)
    max_trades_per_day: int | None = Field(None, gt=0, le=1000)
    pre_trade_checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)
    post_trade_checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)

    @field_validator("instruments")
    @classmethod
    def norm_instruments(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(s.strip().upper() for s in v if s.strip()))

    @model_validator(mode="after")
    def check(self):
        if (self.entry_hour_start is None) != (self.entry_hour_end is None):
            raise ValueError("Set both entry_hour_start and entry_hour_end, or neither")
        if self.entry_hour_start is not None and self.entry_hour_start == self.entry_hour_end:
            raise ValueError("The entry window is empty")
        ids = [i.id for i in self.pre_trade_checklist + self.post_trade_checklist if i.id]
        if len(ids) != len(set(ids)):
            raise ValueError("Checklist item ids must be unique")
        return self

    def to_columns(self) -> dict:
        d = self.model_dump()
        for key in ("pre_trade_checklist", "post_trade_checklist"):
            # Keep ids the client sends (so answers survive edits); generate ids for new items.
            d[key] = [{"id": i["id"] or uuid.uuid4().hex[:8], "text": i["text"].strip()} for i in d[key]]
        return d


class PlaybookIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=20000)
    rules: RulesIn | None = None


class PlaybookPatch(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=20000)
    archived: bool | None = None


class VersionIn(RulesIn):
    change_note: str | None = Field(None, max_length=2000)


class PlaybookOut(ApiModel):
    id: UUID
    name: str
    description: str | None
    current_version: int
    archived_at: datetime | None
    created_at: datetime


def version_out(v: PlaybookVersion) -> dict:
    return {
        "id": v.id, "version": v.version, "change_note": v.change_note, "created_at": v.created_at,
        **{k: getattr(v, k) for k in service.RULE_FIELDS},
    }  # fmt: skip


def detail_out(db: Session, pb: Playbook) -> dict:
    versions = list(db.scalars(select(PlaybookVersion).where(PlaybookVersion.playbook_id == pb.id)
                               .order_by(PlaybookVersion.version.desc())))  # fmt: skip
    atts = list(db.scalars(select(Attachment).where(Attachment.playbook_id == pb.id).order_by(Attachment.created_at)))
    return {
        **PlaybookOut.model_validate(pb).model_dump(),
        "rules": version_out(next(v for v in versions if v.version == pb.current_version)),
        "versions": [
            {"id": v.id, "version": v.version, "change_note": v.change_note, "created_at": v.created_at}
            for v in versions
        ],  # fmt: skip
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at,
            }
            for a in atts
        ],  # fmt: skip
    }


@router.get("", response_model=list[PlaybookOut])
def list_playbooks(
    include_archived: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    q = select(Playbook).where(Playbook.user_id == user.id)
    if not include_archived:
        q = q.where(Playbook.archived_at.is_(None))
    return list(db.scalars(q.order_by(Playbook.name)))


@router.post("", status_code=201)
def create_playbook(data: PlaybookIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pb = Playbook(user_id=user.id, name=data.name.strip(), description=data.description, current_version=0)
    db.add(pb)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A playbook with this name already exists")
    service.add_version(db, pb, (data.rules or RulesIn()).to_columns(), "First version")
    audit.record(db, user_id=user.id, action="playbook.created", entity_type="playbook", entity_id=pb.id)
    db.commit()
    resp = decimal_safe_json(detail_out(db, pb))
    resp.status_code = 201
    return resp


@router.get("/{playbook_id}", summary="Playbook with its current rules, version history and screenshots")
def get_playbook(playbook_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decimal_safe_json(detail_out(db, service.owned_playbook(db, user.id, playbook_id)))


@router.patch("/{playbook_id}", response_model=PlaybookOut)
def patch_playbook(
    playbook_id: UUID, data: PlaybookPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pb = service.owned_playbook(db, user.id, playbook_id)
    ch = data.model_dump(exclude_unset=True)
    archived = ch.pop("archived", None)
    for k, v in ch.items():
        setattr(pb, k, v)
    if archived is not None:
        pb.archived_at = utcnow() if archived else None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("A playbook with this name already exists")
    return pb


@router.post("/{playbook_id}/versions", status_code=201, summary="Save new rules as the next version")
def add_version(
    playbook_id: UUID, data: VersionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Rules are never edited in place. Trades already assigned keep the version they were judged against."""
    pb = service.owned_playbook(db, user.id, playbook_id)
    cols = data.to_columns()
    note = cols.pop("change_note", None)
    v = service.add_version(db, pb, cols, note)
    audit.record(db, user_id=user.id, action="playbook.version_added", entity_type="playbook", entity_id=pb.id,
                 data={"version": v.version})  # fmt: skip
    db.commit()
    resp = decimal_safe_json(version_out(v))
    resp.status_code = 201
    return resp


@router.get("/{playbook_id}/versions/{version}")
def get_version(playbook_id: UUID, version: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pb = service.owned_playbook(db, user.id, playbook_id)
    v = db.scalar(
        select(PlaybookVersion).where(PlaybookVersion.playbook_id == pb.id, PlaybookVersion.version == version)
    )
    if v is None:
        raise NotFound("Playbook version not found")
    return decimal_safe_json(version_out(v))


@router.get("/{pid}/adherence", summary="Rule-adherence report for one playbook under the given filters")
def playbook_adherence(
    pid: UUID,
    f: TradeFilters = Depends(trade_filters),
    currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pb = service.owned_playbook(db, user.id, pid)  # the filters' own playbook_id is replaced by this one
    scoped = replace(f, playbook_ids=[pb.id], no_playbook=False)
    return decimal_safe_json(reports.adherence_report(db, user.id, scoped, currency))


@router.post("/{playbook_id}/attachments", status_code=201, summary="Add a setup screenshot to a playbook")
async def upload_playbook_attachment(
    playbook_id: UUID, file: UploadFile = File(...), user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):  # fmt: skip
    from app.modules.attachments.router import safe_name, sniff

    pb = service.owned_playbook(db, user.id, playbook_id)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large", code="file_too_large")
    ct = sniff(data) if data else None
    if ct is None or not ct.startswith("image/"):
        raise ValidationFailed("Only PNG, JPEG, GIF and WebP images are allowed", code="unsupported_file_type")
    att = Attachment(user_id=user.id, playbook_id=pb.id, storage_key="", filename=safe_name(file.filename or "image"),
                     content_type=ct, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())  # fmt: skip
    db.add(att)
    db.flush()
    att.storage_key = f"attachments/{user.id}/{att.id}"
    get_storage().put(att.storage_key, data, ct)
    audit.record(db, user_id=user.id, action="playbook.attachment_added", entity_type="playbook", entity_id=pb.id)
    db.commit()
    resp = decimal_safe_json({"id": att.id, "filename": att.filename, "content_type": ct, "size_bytes": len(data),
                              "created_at": att.created_at})  # fmt: skip
    resp.status_code = 201
    return resp

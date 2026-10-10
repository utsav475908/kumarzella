from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user
from app.core.errors import Conflict, NotFound
from app.core.schemas import ApiModel
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.playbooks.models import Playbook

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


class PlaybookIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=20000)


class PlaybookPatch(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=20000)
    archived: bool | None = None


class PlaybookOut(ApiModel):
    id: UUID
    name: str
    description: str | None
    current_version: int
    archived_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[PlaybookOut])
def list_playbooks(
    include_archived: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    q = select(Playbook).where(Playbook.user_id == user.id)
    if not include_archived:
        q = q.where(Playbook.archived_at.is_(None))
    return list(db.scalars(q.order_by(Playbook.name)))


@router.post("", response_model=PlaybookOut, status_code=201)
def create_playbook(data: PlaybookIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pb = Playbook(user_id=user.id, name=data.name.strip(), description=data.description)
    db.add(pb)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("A playbook with this name already exists")
    audit.record(db, user_id=user.id, action="playbook.created", entity_type="playbook", entity_id=pb.id)
    db.commit()
    return pb


def _pb(db: Session, user: User, pid: UUID) -> Playbook:
    pb = db.get(Playbook, pid)
    if pb is None or pb.user_id != user.id:
        raise NotFound("Playbook not found")
    return pb


@router.get("/{playbook_id}", response_model=PlaybookOut)
def get_playbook(playbook_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _pb(db, user, playbook_id)


@router.patch("/{playbook_id}", response_model=PlaybookOut)
def patch_playbook(
    playbook_id: UUID, data: PlaybookPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pb = _pb(db, user, playbook_id)
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

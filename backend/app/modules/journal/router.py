from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import Conflict, NotFound
from app.modules.auth.models import User
from app.modules.journal.models import DayNote, Tag, TradeTag
from app.modules.journal.schemas import DayNoteIn, DayNoteOut, TagIn, TagOut, TagPatch

router = APIRouter(tags=["journal"])


@router.get("/tags", response_model=list[TagOut])
def list_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(TradeTag.tag_id, func.count()).where(TradeTag.user_id == user.id).group_by(TradeTag.tag_id)
        ).all()
    )
    tags = db.scalars(select(Tag).where(Tag.user_id == user.id).order_by(Tag.category, Tag.name))
    return [
        TagOut(id=t.id, name=t.name, category=t.category, color=t.color, trade_count=counts.get(t.id, 0)) for t in tags
    ]


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(data: TagIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag = Tag(user_id=user.id, name=data.name.strip(), category=data.category, color=data.color)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("A tag with this name already exists")
    return TagOut(id=tag.id, name=tag.name, category=tag.category, color=tag.color)


def _tag(db: Session, user: User, tag_id: UUID) -> Tag:
    t = db.get(Tag, tag_id)
    if t is None or t.user_id != user.id:
        raise NotFound("Tag not found")
    return t


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(tag_id: UUID, data: TagPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _tag(db, user, tag_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("A tag with this name already exists")
    return TagOut(id=t.id, name=t.name, category=t.category, color=t.color)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_tag(db, user, tag_id))
    db.commit()
    return Response(status_code=204)


@router.get("/day-notes", response_model=list[DayNoteOut])
def list_day_notes(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(DayNote).where(DayNote.user_id == user.id)
    if date_from:
        q = q.where(DayNote.day >= date_from)
    if date_to:
        q = q.where(DayNote.day <= date_to)
    return list(db.scalars(q.order_by(DayNote.day.desc()).limit(limit)))


@router.get("/day-notes/{day}", response_model=DayNoteOut)
def get_day_note(day: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(DayNote).where(DayNote.user_id == user.id, DayNote.day == day))
    if n is None:
        raise NotFound("No note for this day")
    return n


@router.put("/day-notes/{day}", response_model=DayNoteOut)
def put_day_note(day: date, data: DayNoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(DayNote).where(DayNote.user_id == user.id, DayNote.day == day))
    if n is None:
        n = DayNote(user_id=user.id, day=day, body=data.body)
        db.add(n)
    else:
        n.body = data.body
    db.commit()
    return n

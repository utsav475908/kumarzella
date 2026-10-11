"""Per-trade playbook adherence, checklist answers and chart annotations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user
from app.core.errors import NotFound, ValidationFailed
from app.core.schemas import ApiModel, decimal_safe_json
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.instruments.models import Instrument
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.models import Playbook
from app.modules.trades import service
from app.modules.trades.models import Trade, TradeAnnotation

router = APIRouter(prefix="/trades", tags=["trade review"])

ANNOTATION_MARGIN = timedelta(days=7)


class ChecklistAnswerIn(ApiModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    answer: bool | None = Field(description="true = yes, false = no, null = clear the answer")


class ChecklistIn(ApiModel):
    answers: list[ChecklistAnswerIn] = Field(min_length=1, max_length=100)


class TradeAnnotationIn(ApiModel):
    bar_time: datetime
    price: Decimal | None = Field(None, ge=0, max_digits=24, decimal_places=10)
    kind: Literal["note", "mistake", "good"] = "note"
    text: str = Field(min_length=1, max_length=5000)

    @field_validator("bar_time")
    @classmethod
    def aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must include a UTC offset")
        return v.astimezone(UTC)


class TradeAnnotationOut(ApiModel):
    id: UUID
    trade_id: UUID
    bar_time: datetime
    price: Decimal | None
    kind: str
    text: str
    created_at: datetime


def adherence_out(db: Session, t: Trade) -> dict:
    if t.playbook_version_id is None:
        return {"trade_id": t.id, "playbook_id": None, "playbook_name": None, "assessment": None}
    inst = db.get(Instrument, t.instrument_id)
    pb = db.get(Playbook, t.playbook_id)
    assert inst is not None and pb is not None
    a = playbooks.assess_trades(db, [(t, inst)])[t.id]
    return {
        "trade_id": t.id, "playbook_id": pb.id, "playbook_name": pb.name, "current_version": pb.current_version,
        "assessment": a.as_dict(),
    }  # fmt: skip


@router.get("/{trade_id}/adherence", summary="Playbook rule checks and checklist answers for one trade")
def get_adherence(trade_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decimal_safe_json(adherence_out(db, service.get_owned_trade(db, user.id, trade_id)))


@router.put("/{trade_id}/checklist", summary="Answer (or clear) checklist items of the trade's pinned playbook version")
def put_checklist(
    trade_id: UUID, data: ChecklistIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    t = service.get_owned_trade(db, user.id, trade_id)
    playbooks.save_answers(db, t, [(a.item_id, a.answer) for a in data.answers])
    audit.record(db, user_id=user.id, action="trade.checklist_answered", entity_type="trade", entity_id=t.id,
                 data={"items": len(data.answers)})  # fmt: skip
    db.commit()
    return decimal_safe_json(adherence_out(db, t))


@router.get("/{trade_id}/annotations", response_model=list[TradeAnnotationOut])
def list_annotations(trade_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = service.get_owned_trade(db, user.id, trade_id)
    return list(db.scalars(select(TradeAnnotation).where(TradeAnnotation.trade_id == t.id)
                           .order_by(TradeAnnotation.bar_time, TradeAnnotation.created_at)))  # fmt: skip


@router.post("/{trade_id}/annotations", response_model=TradeAnnotationOut, status_code=201)
def add_annotation(
    trade_id: UUID, data: TradeAnnotationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    t = service.get_owned_trade(db, user.id, trade_id)
    lo, hi = t.opened_at - ANNOTATION_MARGIN, (t.closed_at or utcnow()) + ANNOTATION_MARGIN
    if not lo <= data.bar_time <= hi:
        raise ValidationFailed("Annotations must be within 7 days of the trade", code="annotation_out_of_range")
    a = TradeAnnotation(trade_id=t.id, user_id=user.id, bar_time=data.bar_time, price=data.price, kind=data.kind,
                        text=data.text.strip())  # fmt: skip
    db.add(a)
    db.flush()
    audit.record(db, user_id=user.id, action="trade.annotation_added", entity_type="trade", entity_id=t.id)
    db.commit()
    return a


@router.delete("/{trade_id}/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    trade_id: UUID, annotation_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    a = db.get(TradeAnnotation, annotation_id)
    if a is None or a.user_id != user.id or a.trade_id != trade_id:
        raise NotFound("Annotation not found")
    db.delete(a)
    audit.record(db, user_id=user.id, action="trade.annotation_deleted", entity_type="trade", entity_id=trade_id)
    db.commit()
    return Response(status_code=204)

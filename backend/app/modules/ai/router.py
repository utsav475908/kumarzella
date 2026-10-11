"""AI coach API. Every endpoint is scoped to the signed-in user; reviews of other users are 404."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import NotFound
from app.core.schemas import ApiModel
from app.modules.ai import client as ai_client
from app.modules.ai import coach
from app.modules.ai.models import AiEvidence, AiReview
from app.modules.ai.tools import FILTERS
from app.modules.auth.models import User
from app.modules.instruments.models import Instrument
from app.modules.trades import service as trades

router = APIRouter(prefix="/ai", tags=["ai coach"])

FILTER_KEYS = tuple(FILTERS["properties"])


class EvidenceOut(ApiModel):
    ref: str
    tool: str
    label: str
    input: dict
    filters: dict
    sample_size: int | None
    result: dict


class ReviewOut(ApiModel):
    id: UUID
    kind: str
    trade_id: UUID | None
    period_from: date | None
    period_to: date | None
    question: str
    answer: str
    status: str
    limitations: list[str]
    suggested_tags: list[dict]
    cited: list[str]
    unsupported_numbers: list[str]
    model: str
    usage: dict
    created_at: datetime
    evidence: list[EvidenceOut] = []


class ReviewSummary(ApiModel):
    id: UUID
    kind: str
    trade_id: UUID | None
    period_from: date | None
    period_to: date | None
    question: str
    status: str
    created_at: datetime


class AskIn(ApiModel):
    question: str = Field(min_length=3, max_length=2000)
    # Optional page context, e.g. the dashboard's current filters. Same keys as the coach's filter tool input.
    filters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _keys(self):
        if self.filters:
            self.filters = {k: v for k, v in self.filters.items() if k in FILTER_KEYS and v not in (None, "", [])}
        return self


class SummaryIn(ApiModel):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _range(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if (self.date_to - self.date_from).days > 92:
            raise ValueError("Summaries cover at most 92 days")
        return self


def _out(db: Session, r: AiReview) -> ReviewOut:
    ev = db.scalars(select(AiEvidence).where(AiEvidence.review_id == r.id).order_by(AiEvidence.created_at))
    rows = sorted(ev, key=lambda e: int(e.ref[1:]))
    return ReviewOut.model_validate({**{c.key: getattr(r, c.key) for c in AiReview.__table__.columns},
                                     "evidence": [EvidenceOut.model_validate(e) for e in rows]})  # fmt: skip


def _owned(db: Session, user: User, review_id: UUID) -> AiReview:
    r = db.get(AiReview, review_id)
    if r is None or r.user_id != user.id:
        raise NotFound("Review not found")
    return r


@router.get("/status", summary="Whether the AI coach is configured")
def status(user: User = Depends(get_current_user)):
    s = get_settings()
    c = ai_client.active()
    return {
        "enabled": c is not None,
        "provider": getattr(c, "provider", "test") if c else None,
        "model": (getattr(c, "model", None) or s.ai_model) if c else None,
        "fallbacks": s.ai_fallbacks and getattr(c, "provider", None) == "anthropic",
        "reason": None if c else "No AI key is configured on the server (OPENAI_API_KEY or ANTHROPIC_API_KEY).",
        "limits": {"requests_per_hour": s.ai_rate_limit, "tool_rounds": s.ai_max_tool_rounds},
    }


@router.post("/ask", response_model=ReviewOut, status_code=201, summary="Ask the coach about your own trading")
def ask(data: AskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prompt = data.question
    if data.filters:
        prompt += ("\n\nThe trader is looking at a page filtered by: " + ", ".join(f"{k}={v}" for k, v in
                   data.filters.items()) + ". Use these filters unless the question says otherwise.")  # fmt: skip
    return _out(db, coach.ask(db, user.id, kind="ask", prompt=prompt, question=data.question))


@router.post("/trades/{trade_id}/review", response_model=ReviewOut, status_code=201, summary="AI review of a trade")
def review_trade(trade_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = trades.get_owned_trade(db, user.id, trade_id)
    inst = db.get(Instrument, t.instrument_id)
    assert inst is not None
    (out,) = trades.to_out(db, [(t, inst)])
    prompt = (
        f"Review this trade: trade_id {t.id}. Call get_trade first. Then compare it with the trader's other "
        "trades where that helps (same symbol, same playbook or same direction) using performance_summary or "
        "list_trades. Cover: what happened, whether risk and the playbook's rules were respected, what went well, "
        "and what to review next time. Then call tags_and_playbooks and suggest up to 3 tags that describe this "
        "trade (setup, mistake or emotion) and that it doesn't already carry."
    )
    question = f"Review of {inst.symbol} {t.direction} trade on {t.session_date}"
    return _out(db, coach.ask(db, user.id, kind="trade_review", prompt=prompt, question=question, trade_id=t.id,
                              current_tags={g.name.lower() for g in out.tags}))  # fmt: skip


@router.post("/summary", response_model=ReviewOut, status_code=201, summary="AI summary of a day or week")
def summary(data: SummaryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    one_day = data.date_from == data.date_to
    span = f"{data.date_from}" if one_day else f"{data.date_from} to {data.date_to}"
    prompt = (
        f"Summarise the trader's {'day' if one_day else 'period'} {span}. Call period_summary with date_from "
        f"{data.date_from} and date_to {data.date_to}. Cover the result, the best and worst trades, any broken risk "
        "limits or rules, what the day notes say, and one to three things to focus on next."
    )
    return _out(db, coach.ask(db, user.id, kind="period_summary", prompt=prompt, question=f"Summary of {span}",
                              period=(data.date_from, data.date_to)))  # fmt: skip


@router.get("/reviews", response_model=list[ReviewSummary], summary="Your past coach answers, newest first")
def list_reviews(
    trade_id: UUID | None = None,
    kind: Literal["ask", "trade_review", "period_summary"] | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(AiReview).where(AiReview.user_id == user.id)
    if trade_id:
        q = q.where(AiReview.trade_id == trade_id)
    if kind:
        q = q.where(AiReview.kind == kind)
    return list(db.scalars(q.order_by(AiReview.created_at.desc()).limit(limit)))


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(db, _owned(db, user, review_id))


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review(review_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_owned(db, user, review_id))
    db.commit()
    return Response(status_code=204)

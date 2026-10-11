from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user
from app.core.errors import NotFound, ValidationFailed
from app.core.schemas import ApiModel, decimal_safe_json
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.instruments.models import Instrument
from app.modules.marketdata import service as md
from app.modules.marketdata import trade_chart
from app.modules.marketdata.providers import get_provider
from app.modules.playbooks.models import Playbook
from app.modules.replay import service as rp
from app.modules.replay.models import ReplayAnnotation, ReplaySession
from app.modules.trades import service as trades

router = APIRouter(prefix="/replay", tags=["replay"])

Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "4h"]
MAX_BLIND = timedelta(days=md.MAX_RANGE_DAYS)


class SessionIn(ApiModel):
    mode: Literal["review", "blind"]
    trade_id: UUID | None = None
    symbol: str | None = Field(None, max_length=32)
    timeframe: Timeframe = "1m"
    side: Literal["bid", "ask", "mid"] = "bid"
    start_at: datetime | None = None
    end_at: datetime | None = None
    title: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def check_mode(self):
        if self.mode == "review" and self.trade_id is None:
            raise ValueError("A review replay needs trade_id")
        if self.mode == "blind":
            if self.trade_id is not None:
                raise ValueError("A blind replay is not tied to a trade; use review mode to replay a trade")
            if not (self.symbol and self.start_at and self.end_at):
                raise ValueError("A blind replay needs symbol, start_at and end_at")
        return self


class SessionPatch(ApiModel):
    speed: int | None = Field(None, ge=1, le=64)
    cursor_at: datetime | None = None
    title: str | None = Field(None, min_length=1, max_length=200)


class AdvanceIn(ApiModel):
    steps: int = Field(1, ge=1, le=64)


class AnnotationIn(ApiModel):
    bar_time: datetime
    price: Decimal | None = None
    text: str = Field(min_length=1, max_length=5000)


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _owned(db: Session, user: User, sid: UUID) -> ReplaySession:
    rs = db.get(ReplaySession, sid)
    if rs is None or rs.user_id != user.id:
        raise NotFound("Replay session not found")
    return rs


def session_out(rs: ReplaySession) -> dict:
    return {
        "id": rs.id, "mode": rs.mode, "trade_id": rs.trade_id, "title": rs.title, "provider": rs.provider,
        "symbol": rs.symbol, "timeframe": rs.timeframe, "side": rs.side, "start_at": rs.start_at,
        "end_at": rs.end_at, "cursor_at": rs.cursor_at, "speed": rs.speed, "completed": rs.completed_at is not None,
        "progress": rp.progress(rs), "created_at": rs.created_at, "updated_at": rs.updated_at,
    }  # fmt: skip


def _provider():
    p = get_provider()
    if p is None:
        raise ValidationFailed("Historical market data is disabled", code="marketdata_disabled")
    return p


@router.get("/sessions")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ReplaySession).where(ReplaySession.user_id == user.id).order_by(ReplaySession.updated_at.desc())
    )
    return decimal_safe_json([session_out(r) for r in rows])


@router.post("/sessions", status_code=201)
def create_session(data: SessionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _provider()
    now = utcnow()
    if data.mode == "review":
        assert data.trade_id is not None
        t = trades.get_owned_trade(db, user.id, data.trade_id)
        inst = db.get(Instrument, t.instrument_id)
        assert inst is not None
        psym = p.provider_symbol(inst.symbol, inst.asset_class)
        if psym is None:
            raise ValidationFailed(f"{p.info.display_name} has no data for {inst.symbol}", code="symbol_not_supported")
        w = trade_chart.trade_window(t, data.timeframe, now)
        start, end = w.start, rp.align(w.end, data.timeframe)
        title = data.title or f"Review {inst.symbol} {t.direction} {t.opened_at:%Y-%m-%d %H:%M} UTC"
    else:
        assert data.symbol and data.start_at and data.end_at
        psym = p.provider_symbol(data.symbol, "forex")
        if psym is None:
            raise ValidationFailed(f"{p.info.display_name} has no data for {data.symbol}", code="symbol_not_supported")
        start, end = rp.align(_utc(data.start_at), data.timeframe), rp.align(_utc(data.end_at), data.timeframe)
        if end <= start:
            raise ValidationFailed("end_at must be after start_at")
        if end - start > MAX_BLIND:
            raise ValidationFailed(f"A blind replay can cover at most {md.MAX_RANGE_DAYS} days")
        if end.date() >= now.date():
            raise ValidationFailed("A blind replay must end before today (UTC); only completed days are published")
        title = data.title or f"Blind {psym} {data.timeframe} from {start:%Y-%m-%d}"
    if end <= start:
        raise ValidationFailed("The replay window is empty")
    rs = ReplaySession(
        user_id=user.id, mode=data.mode, trade_id=data.trade_id, title=title, provider=p.info.name, symbol=psym,
        timeframe=data.timeframe, side=data.side, start_at=start, end_at=end, cursor_at=start, speed=1,
    )  # fmt: skip
    cov = md.ensure_range(db, p, psym, start, end)
    if cov.status != "pending":
        rs.cursor_at = rp.initial_cursor(db, rs)
    db.add(rs)
    db.flush()
    audit.record(db, user_id=user.id, action="replay.created", entity_type="replay_session", entity_id=rs.id,
                 data={"mode": rs.mode})  # fmt: skip
    db.commit()
    resp = decimal_safe_json(session_out(rs) | {"coverage": md.coverage_out(cov)})
    resp.status_code = 201
    return resp


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decimal_safe_json(session_out(_owned(db, user, session_id)))


@router.get("/sessions/{session_id}/bars", summary="Bars for the player: all bars in review, revealed bars in blind")
def session_bars(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rs = _owned(db, user, session_id)
    p = _provider()
    cov = md.ensure_range(db, p, rs.symbol, rs.start_at, rs.end_at)
    body: dict = session_out(rs) | {"status": cov.status, "coverage": md.coverage_out(cov),
                                    "provider": trade_chart.provider_out(p)}  # fmt: skip
    if cov.status == "pending":
        resp = decimal_safe_json(body | {"bars": [], "markers": [], "overlay": None})
        resp.status_code = 202
        return resp
    if rs.mode == "blind" and rs.cursor_at == rs.start_at and rs.completed_at is None:
        # Data arrived after creation (worker fetch): place the warm-up cursor now.
        rs.cursor_at = rp.initial_cursor(db, rs)
        db.commit()
        body = body | session_out(rs)
    bars = rp.all_bars(db, rs) if rs.mode == "review" else rp.bars_until_cursor(db, rs)
    markers: list[dict] = []
    overlay = None
    if rs.mode == "review" and rs.trade_id:
        t = trades.get_owned_trade(db, user.id, rs.trade_id)
        markers = [
            {
                "t": int(f.ts.timestamp()),
                "ts": f.ts,
                "side": "buy" if f.signed_qty > 0 else "sell",
                "quantity": abs(f.signed_qty),
                "price": f.price,
            }  # fmt: skip
            for f in trade_chart.fill_points(db, t)
        ]
        pb = db.get(Playbook, t.playbook_id) if t.playbook_id else None
        overlay = {"planned_stop_price": t.planned_stop_price, "planned_target_price": t.planned_target_price,
                   "entry_avg_price": t.entry_avg_price, "exit_avg_price": t.exit_avg_price,
                   "playbook": pb.name if pb else None, "direction": t.direction}  # fmt: skip
    return decimal_safe_json(body | {"bars": [md.bar_out(b) for b in bars], "markers": markers, "overlay": overlay})


@router.post("/sessions/{session_id}/advance", summary="Reveal the next bars (blind) or move the saved cursor")
def advance(session_id: UUID, data: AdvanceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rs = _owned(db, user, session_id)
    new = rp.advance(db, rs, data.steps)
    if rs.cursor_at >= rs.end_at and rs.completed_at is None:
        rs.completed_at = utcnow()
    db.commit()
    return decimal_safe_json(session_out(rs) | {"bars": [md.bar_out(b) for b in new]})


@router.patch(
    "/sessions/{session_id}", summary="Save speed or seek. Blind sessions reveal everything up to a new cursor"
)
def patch_session(
    session_id: UUID, data: SessionPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rs = _owned(db, user, session_id)
    if data.speed is not None:
        rs.speed = data.speed
    if data.title is not None:
        rs.title = data.title
    if data.cursor_at is not None:
        c = rp.align(_utc(data.cursor_at), rs.timeframe)
        rs.cursor_at = min(max(c, rs.start_at), rs.end_at)
        if rs.cursor_at >= rs.end_at and rs.completed_at is None:
            rs.completed_at = utcnow()
    db.commit()
    return decimal_safe_json(session_out(rs))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rs = _owned(db, user, session_id)
    db.delete(rs)
    audit.record(db, user_id=user.id, action="replay.deleted", entity_type="replay_session", entity_id=session_id)
    db.commit()
    return Response(status_code=204)


def annotation_out(a: ReplayAnnotation) -> dict:
    return {"id": a.id, "bar_time": a.bar_time, "t": int(a.bar_time.timestamp()), "price": a.price, "text": a.text,
            "created_at": a.created_at}  # fmt: skip


@router.get("/sessions/{session_id}/annotations")
def list_annotations(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rs = _owned(db, user, session_id)
    rows = db.scalars(
        select(ReplayAnnotation).where(ReplayAnnotation.session_id == rs.id).order_by(ReplayAnnotation.bar_time)
    )
    return decimal_safe_json([annotation_out(a) for a in rows])


@router.post("/sessions/{session_id}/annotations", status_code=201)
def add_annotation(
    session_id: UUID, data: AnnotationIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rs = _owned(db, user, session_id)
    bar_time = _utc(data.bar_time)
    if not (rs.start_at <= bar_time <= rs.end_at):
        raise ValidationFailed("The annotation is outside the replay window")
    if rs.mode == "blind" and bar_time > rs.cursor_at:
        raise ValidationFailed("You can only annotate bars that have been revealed")
    a = ReplayAnnotation(session_id=rs.id, user_id=user.id, bar_time=bar_time, price=data.price, text=data.text)
    db.add(a)
    db.commit()
    resp = decimal_safe_json(annotation_out(a))
    resp.status_code = 201
    return resp


@router.delete("/sessions/{session_id}/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    session_id: UUID, annotation_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rs = _owned(db, user, session_id)
    a = db.get(ReplayAnnotation, annotation_id)
    if a is None or a.session_id != rs.id:
        raise NotFound("Annotation not found")
    db.delete(a)
    db.commit()
    return Response(status_code=204)

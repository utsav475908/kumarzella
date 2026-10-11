import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import get_current_user
from app.core.errors import Conflict, ValidationFailed
from app.core.schemas import ApiModel, decimal_safe_json
from app.core.storage import get_storage
from app.modules.attachments.models import Attachment
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.backtesting import service as bt
from app.modules.backtesting.models import BacktestFill, BacktestOrder, BacktestSession, BacktestTrade
from app.modules.marketdata import service as md
from app.modules.marketdata import trade_chart
from app.modules.marketdata.providers import get_provider
from app.modules.replay import service as rp

router = APIRouter(prefix="/backtests", tags=["backtesting"])
MAX_WINDOW = timedelta(days=md.MAX_RANGE_DAYS)
Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "4h"]


class SessionIn(ApiModel):
    symbol: str = Field(min_length=6, max_length=32)
    timeframe: Timeframe = "5m"
    start_at: datetime
    end_at: datetime
    starting_balance: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    commission_per_100k: Decimal = Field(Decimal(0), ge=0, le=1000)
    slippage_pips: Decimal = Field(Decimal(0), ge=0, le=100)
    title: str | None = Field(None, max_length=200)


class SessionPatch(ApiModel):
    cursor_at: datetime | None = Field(None, description="Jump forward; orders still fill in the skipped bars")
    speed: int | None = Field(None, ge=1, le=64)
    title: str | None = Field(None, min_length=1, max_length=200)
    notes: str | None = Field(None, max_length=50000)


class AdvanceIn(ApiModel):
    steps: int = Field(1, ge=1, le=64)


class OrderIn(ApiModel):
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop"] = "market"
    quantity: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=2)
    risk_amount: Decimal | None = Field(None, gt=0, max_digits=16, decimal_places=2)
    price: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=10)
    stop_loss: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=10)
    take_profit: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=10)
    note: str | None = Field(None, max_length=5000)


class FinishIn(ApiModel):
    flatten: bool = Field(True, description="Close an open position at the last revealed close")


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _provider():
    p = get_provider()
    if p is None:
        raise ValidationFailed("Historical market data is disabled", code="marketdata_disabled")
    return p


def session_out(bs: BacktestSession) -> dict:
    return {
        "id": bs.id, "title": bs.title, "provider": bs.provider, "symbol": bs.symbol, "timeframe": bs.timeframe,
        "side": bs.side, "start_at": bs.start_at, "end_at": bs.end_at, "cursor_at": bs.cursor_at, "speed": bs.speed,
        "currency": bs.currency, "starting_balance": bs.starting_balance, "config": bs.config, "notes": bs.notes,
        "status": bs.status, "completed_at": bs.completed_at, "at_end": bs.cursor_at >= bs.end_at,
        "progress": rp.progress(bs), "pip_size": bt.pip_size(bs.symbol),  # type: ignore[arg-type]
        "created_at": bs.created_at, "updated_at": bs.updated_at,
    }  # fmt: skip


def order_out(o: BacktestOrder) -> dict:
    return {
        "id": o.id, "seq": o.seq, "kind": o.kind, "parent_id": o.parent_id, "side": o.side, "type": o.type,
        "quantity": o.quantity, "price": o.price, "stop_loss": o.stop_loss, "take_profit": o.take_profit,
        "risk_amount": o.risk_amount, "placed_at": o.placed_at, "status": o.status, "cancelled_at": o.cancelled_at,
        "reason": o.reason, "note": o.note,
    }  # fmt: skip


def fill_out(f: BacktestFill, kinds: dict) -> dict:
    return {
        "id": f.id, "order_id": f.order_id, "kind": kinds.get(f.order_id, "finish"), "t": int(f.ts.timestamp()),
        "ts": f.ts, "side": f.side, "quantity": f.quantity, "price": f.price, "commission": f.commission,
        "slippage": f.slippage, "ambiguous": f.ambiguous, "reason": f.reason,
    }  # fmt: skip


def trade_out(t: BacktestTrade) -> dict:
    return {c: getattr(t, c) for c in ("id", "number", "direction", "status", "opened_at", "closed_at", "entry_qty",
                                       "entry_avg_price", "exit_avg_price", "gross_pnl", "fees", "net_pnl",
                                       "initial_risk", "r_multiple", "ambiguous")}  # fmt: skip


def state_out(db: Session, bs: BacktestSession) -> dict:
    os_ = bt.orders(db, bs)
    kinds = {o.id: o.kind for o in os_}
    q = bt.last_quote(db, bs)
    return {
        "session": session_out(bs),
        "position": bt.position(db, bs),
        "open_pnl": bt.open_pnl(db, bs),
        "quote": {"t": int(q[0].ts.timestamp()), "bid": q[0].close, "ask": q[1].close} if q else None,
        "orders": [order_out(o) for o in os_],
        "fills": [fill_out(f, kinds) for f in bt.fills(db, bs)],
        "trades": [trade_out(t) for t in bt.trades(db, bs)],
    }


def events_out(ev) -> dict:
    return {"fills": len(ev.fills), "cancels": len(ev.cancels), "ambiguous": sum(1 for f in ev.fills if f.ambiguous)}


@router.get("")
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(BacktestSession).where(BacktestSession.user_id == user.id)
                      .order_by(BacktestSession.updated_at.desc()))  # fmt: skip
    out = []
    for bs in rows:
        closed = [t for t in bt.trades(db, bs) if t.status == "closed"]
        out.append(session_out(bs) | {"closed_trades": len(closed),
                                      "net_pnl": sum((t.net_pnl for t in closed), Decimal(0))})  # fmt: skip
    return decimal_safe_json(out)


@router.post("", status_code=201)
def create_session(data: SessionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _provider()
    psym = p.provider_symbol(data.symbol.upper(), "forex")
    if psym is None:
        raise ValidationFailed(f"{p.info.display_name} has no data for {data.symbol}", code="symbol_not_supported")
    start, end = rp.align(_utc(data.start_at), data.timeframe), rp.align(_utc(data.end_at), data.timeframe)
    now = utcnow()
    if end <= start:
        raise ValidationFailed("end_at must be after start_at")
    if end - start > MAX_WINDOW:
        raise ValidationFailed(f"A backtest can cover at most {md.MAX_RANGE_DAYS} days")
    if end.date() >= now.date():
        raise ValidationFailed("A backtest must end before today (UTC); only completed days are published")
    bs = BacktestSession(
        user_id=user.id, title=data.title or f"{psym} {data.timeframe} from {start:%Y-%m-%d}", provider=p.info.name,
        symbol=psym, timeframe=data.timeframe, side="bid", start_at=start, end_at=end, cursor_at=start, speed=1,
        currency=psym[3:6], starting_balance=data.starting_balance,
        config=bt.make_config(psym, data.commission_per_100k, data.slippage_pips, p.info.name),
    )  # fmt: skip
    cov = md.ensure_range(db, p, psym, start, end)
    if cov.status != "pending":
        bs.cursor_at = rp.initial_cursor(db, bs)  # type: ignore[arg-type]
    db.add(bs)
    db.flush()
    audit.record(db, user_id=user.id, action="backtest.created", entity_type="backtest_session", entity_id=bs.id)
    db.commit()
    resp = decimal_safe_json(session_out(bs) | {"coverage": md.coverage_out(cov)})
    resp.status_code = 201
    return resp


@router.get("/{sid}", summary="Session, position, orders, fills and simulated trades")
def get_session(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decimal_safe_json(state_out(db, bt.owned(db, user.id, sid)))


@router.patch("/{sid}")
def patch_session(sid: UUID, data: SessionPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    ev = None
    if data.cursor_at is not None:
        bt.require_active(bs)
        target = min(rp.align(_utc(data.cursor_at), bs.timeframe), bs.end_at)
        if target < bs.cursor_at:
            raise ValidationFailed("A backtest cannot go back in time", code="cursor_backwards")
        if md.ensure_range(db, _provider(), bs.symbol, bs.start_at, bs.end_at).status == "pending":
            raise Conflict("Market data for this session is still downloading")
        ev = bt.move_cursor(db, bs, target)
    for k in ("speed", "title", "notes"):
        if k in data.model_fields_set and getattr(data, k) is not None:
            setattr(bs, k, getattr(data, k))
    db.commit()
    return decimal_safe_json(state_out(db, bs) | {"events": events_out(ev) if ev else None})


@router.delete("/{sid}", status_code=204)
def delete_session(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    keys = list(db.scalars(select(Attachment.storage_key).where(Attachment.backtest_session_id == bs.id)))
    db.delete(bs)
    audit.record(db, user_id=user.id, action="backtest.deleted", entity_type="backtest_session", entity_id=sid)
    db.commit()
    for k in keys:
        get_storage().delete(k)
    return Response(status_code=204)


@router.get("/{sid}/bars", summary="Revealed bars only, with simulated fills as markers")
def session_bars(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    p = _provider()
    cov = md.ensure_range(db, p, bs.symbol, bs.start_at, bs.end_at)
    body = {"session": session_out(bs), "status": cov.status, "coverage": md.coverage_out(cov),
            "provider": trade_chart.provider_out(p)}  # fmt: skip
    if cov.status == "pending":
        resp = decimal_safe_json(body | {"bars": []})
        resp.status_code = 202
        return resp
    if bs.cursor_at == bs.start_at and bs.status == "active" and not bt.orders(db, bs):
        bs.cursor_at = rp.initial_cursor(db, bs)  # type: ignore[arg-type]  # data arrived after creation
        db.commit()
        body["session"] = session_out(bs)
    bars = rp.bars_until_cursor(db, bs)  # type: ignore[arg-type]
    return decimal_safe_json(body | {"bars": [md.bar_out(b) for b in bars]})


@router.post("/{sid}/advance", summary="Reveal the next bars and run the simulator over them")
def advance(sid: UUID, data: AdvanceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    if md.ensure_range(db, _provider(), bs.symbol, bs.start_at, bs.end_at).status == "pending":
        raise Conflict("Market data for this session is still downloading")
    new, ev = bt.advance(db, bs, data.steps)
    db.commit()
    return decimal_safe_json(state_out(db, bs) | {"bars": [md.bar_out(b) for b in new], "events": events_out(ev)})


@router.post("/{sid}/orders", status_code=201, summary="Place a simulated order at the cursor")
def place_order(sid: UUID, data: OrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    o = bt.place_order(db, bs, side=data.side, type_=data.type, quantity=data.quantity, risk_amount=data.risk_amount,
                       price=data.price, stop_loss=data.stop_loss, take_profit=data.take_profit, note=data.note)  # fmt: skip
    db.commit()
    resp = decimal_safe_json(state_out(db, bs) | {"order": order_out(o)})
    resp.status_code = 201
    return resp


@router.post("/{sid}/orders/{oid}/cancel")
def cancel_order(sid: UUID, oid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    bt.cancel_order(db, bs, oid)
    db.commit()
    return decimal_safe_json(state_out(db, bs))


@router.post("/{sid}/finish", summary="End the session; optionally close the open position at the last close")
def finish(sid: UUID, data: FinishIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    bt.finish(db, bs, data.flatten)
    audit.record(db, user_id=user.id, action="backtest.finished", entity_type="backtest_session", entity_id=bs.id)
    db.commit()
    return decimal_safe_json(state_out(db, bs))


@router.get("/{sid}/results", summary="Performance of the simulated trades; computed by the analytics module")
def results(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    return decimal_safe_json({"session": session_out(bs), **bt.results(db, bs),
                              "trades": [trade_out(t) for t in bt.trades(db, bs)]})  # fmt: skip


@router.get("/{sid}/verify", summary="Re-run the session from its order log and compare with the stored fills")
def verify(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return decimal_safe_json(bt.verify(db, bt.owned(db, user.id, sid)))


@router.post("/{sid}/attachments", status_code=201, summary="Add a screenshot to a backtest session")
async def upload_attachment(sid: UUID, file: UploadFile = File(...), user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):  # fmt: skip
    from app.modules.attachments.router import safe_name, sniff

    bs = bt.owned(db, user.id, sid)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large", code="file_too_large")
    ct = sniff(data) if data else None
    if ct is None or not ct.startswith("image/"):
        raise ValidationFailed("Only PNG, JPEG, GIF and WebP images are allowed", code="unsupported_file_type")
    att = Attachment(user_id=user.id, backtest_session_id=bs.id, storage_key="", filename=safe_name(file.filename or "image"),
                     content_type=ct, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())  # fmt: skip
    db.add(att)
    db.flush()
    att.storage_key = f"attachments/{user.id}/{att.id}"
    get_storage().put(att.storage_key, data, ct)
    db.commit()
    resp = decimal_safe_json({"id": att.id, "filename": att.filename, "content_type": ct, "size_bytes": len(data),
                              "created_at": att.created_at})  # fmt: skip
    resp.status_code = 201
    return resp


@router.get("/{sid}/attachments")
def list_attachments(sid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs = bt.owned(db, user.id, sid)
    atts = db.scalars(select(Attachment).where(Attachment.backtest_session_id == bs.id).order_by(Attachment.created_at))
    return decimal_safe_json([{"id": a.id, "filename": a.filename, "content_type": a.content_type,
                               "size_bytes": a.size_bytes, "created_at": a.created_at} for a in atts])  # fmt: skip

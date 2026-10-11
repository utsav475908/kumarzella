from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, owned_account
from app.core.errors import ValidationFailed
from app.core.schemas import ApiModel, decimal_safe_json
from app.modules.auth.models import User
from app.modules.instruments.models import Instrument
from app.modules.marketdata import service as md
from app.modules.marketdata import trade_chart
from app.modules.marketdata.bars import TIMEFRAMES
from app.modules.marketdata.providers import get_provider
from app.modules.trades import service as trades
from app.modules.trades.models import Trade

router = APIRouter(prefix="/marketdata", tags=["market data"])
trade_router = APIRouter(prefix="/trades", tags=["trades"])

Timeframe = Literal["1m", "5m", "15m", "30m", "1h", "4h"]
Side = Literal["bid", "ask", "mid"]


@router.get("/provider", summary="The configured historical-data provider, its coverage and licence terms")
def provider_info(user: User = Depends(get_current_user)):
    p = get_provider()
    if p is None:
        return {"enabled": False, "provider": None, "timeframes": list(TIMEFRAMES)}
    from app.modules.marketdata.providers.dukascopy import PAIRS

    return {"enabled": True, "provider": trade_chart.provider_out(p), "timeframes": list(TIMEFRAMES),
            "symbols": list(PAIRS) if p.info.name == "dukascopy" else []}  # fmt: skip


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


@router.get("/candles", summary="Cached historical candles for a symbol (fetched on demand)")
def candles(
    symbol: str,
    start: datetime,
    end: datetime,
    asset_class: str = "forex",
    timeframe: Timeframe = "1m",
    side: Side = "bid",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = get_provider()
    if p is None:
        raise ValidationFailed("Historical market data is disabled", code="marketdata_disabled")
    psym = p.provider_symbol(symbol, asset_class)
    if psym is None:
        raise ValidationFailed(f"{p.info.display_name} does not cover {symbol}", code="symbol_not_supported")
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValidationFailed("end must be after start")
    if end - start > timedelta(days=md.MAX_RANGE_DAYS):
        raise ValidationFailed(f"Request at most {md.MAX_RANGE_DAYS} days at a time")
    cov = md.ensure_range(db, p, psym, start, end)
    bars = md.load_bars(db, p.info.name, psym, side, start, end, timeframe)
    if len(bars) > md.MAX_BARS:
        raise ValidationFailed("Too many bars: choose a larger timeframe or a shorter range", code="too_many_bars")
    minutes = md.load_minutes(db, p.info.name, psym, "bid", start, end) if bars else []
    body = {
        "status": cov.status, "provider": trade_chart.provider_out(p), "symbol": psym, "timeframe": timeframe,
        "side": side, "start": start, "end": end, "coverage": md.coverage_out(cov),
        "bars": [md.bar_out(b) for b in bars], "gaps": md.gaps_out(minutes, start, end),
    }  # fmt: skip
    resp = decimal_safe_json(body)
    if cov.status == "pending":
        resp.status_code = 202
    return resp


@trade_router.get("/{trade_id}/chart", summary="Candles around a trade, fills as markers, MAE/MFE when available")
def trade_chart_endpoint(
    trade_id: UUID,
    timeframe: Timeframe = "1m",
    side: Side = "bid",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = trades.get_owned_trade(db, user.id, trade_id)
    body = trade_chart.build(db, t, timeframe, side)
    resp = decimal_safe_json(body)
    if body["status"] == "pending":
        resp.status_code = 202
    return resp


class ExcursionRefresh(ApiModel):
    account_id: UUID | None = None
    limit: int = Field(200, ge=1, le=1000)


@router.post("/excursions/refresh", summary="Compute MAE/MFE for closed trades the provider covers")
def refresh_excursions(data: ExcursionRefresh, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = get_provider()
    if p is None:
        raise ValidationFailed("Historical market data is disabled", code="marketdata_disabled")
    q = (
        select(Trade, Instrument)
        .join(Instrument, Instrument.id == Trade.instrument_id)
        .where(
            Trade.user_id == user.id,
            Trade.status == "closed",
            Trade.mae.is_(None),
            Instrument.asset_class.in_(p.info.asset_classes),
        )  # fmt: skip
        .order_by(Trade.closed_at.desc())
        .limit(data.limit)
    )
    if data.account_id:
        owned_account(db, user, data.account_id)
        q = q.where(Trade.account_id == data.account_id)
    computed = pending = skipped = 0
    for t, inst in db.execute(q).all():
        psym = p.provider_symbol(inst.symbol, inst.asset_class)
        if psym is None or t.closed_at is None:
            skipped += 1
            continue
        if trade_chart.maybe_store_excursions(db, t, p, psym) is not None:
            computed += 1
        else:
            pending += 1
    return {"computed": computed, "pending_or_incomplete": pending, "unsupported": skipped}

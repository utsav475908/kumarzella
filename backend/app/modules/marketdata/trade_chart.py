"""Candles around one trade, its fills as markers, and MAE/MFE when the data is complete."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.analytics import excursions as ex
from app.modules.executions.models import Execution
from app.modules.instruments.models import Instrument
from app.modules.marketdata import bars as bx
from app.modules.marketdata import service as md
from app.modules.marketdata.providers import get_provider
from app.modules.marketdata.providers.base import MarketDataProvider
from app.modules.trades.models import Trade, TradeExecution

MIN_PAD_BARS = 40
MAX_WINDOW = timedelta(days=md.MAX_RANGE_DAYS)


@dataclass
class Window:
    start: datetime
    end: datetime


def trade_window(t: Trade, timeframe: str, now: datetime) -> Window:
    tf = timedelta(seconds=bx.tf_seconds(timeframe))
    end = t.closed_at or now
    pad = max(tf * MIN_PAD_BARS, (end - t.opened_at) * 0.25)
    start = bx.bucket_start(t.opened_at - pad, bx.tf_seconds(timeframe))
    stop = min(end + pad, now)
    if stop - start > MAX_WINDOW:
        start = max(start, end - MAX_WINDOW)
    return Window(start, stop)


def fill_points(db: Session, t: Trade) -> list[ex.FillPoint]:
    rows = db.execute(
        select(TradeExecution.quantity, Execution.side, Execution.price, Execution.executed_at)
        .join(Execution, Execution.id == TradeExecution.execution_id)
        .where(TradeExecution.trade_id == t.id)
        .order_by(Execution.executed_at, Execution.sequence, Execution.id)
    ).all()
    return [ex.FillPoint(ts, q if side == "buy" else -q, p) for q, side, p, ts in rows]


def unsupported(reason: str, provider: MarketDataProvider | None) -> dict:
    return {
        "status": "unsupported",
        "reason": reason,
        "provider": provider_out(provider) if provider else None,
        "bars": [],
        "markers": [],
    }


def provider_out(p: MarketDataProvider) -> dict:
    i = p.info
    return {
        "name": i.name, "display_name": i.display_name, "asset_classes": list(i.asset_classes),
        "granularity": i.granularity, "sides": list(i.sides), "attribution": i.attribution,
        "licence_note": i.licence_note, "volume_note": i.volume_note,
    }  # fmt: skip


def maybe_store_excursions(db: Session, t: Trade, provider: MarketDataProvider, symbol: str) -> ex.Excursions | None:
    """Compute and persist MAE/MFE when the trade is closed and every day of its holding period is cached."""
    if t.status != "closed" or t.closed_at is None:
        return None
    held = md.ensure_range(db, provider, symbol, t.opened_at, t.closed_at + timedelta(minutes=1))
    if not held.complete:
        return None
    end = bx.bucket_start(t.closed_at, 60) + timedelta(minutes=1)
    name = provider.info.name
    bid = md.load_minutes(db, name, symbol, "bid", t.opened_at, end)
    ask = md.load_minutes(db, name, symbol, "ask", t.opened_at, end)
    inst = db.get(Instrument, t.instrument_id)
    assert inst is not None
    result = ex.compute(fill_points(db, t), inst.multiplier, bid, ask)
    if result is None:
        return None
    t.mae, t.mfe = result.mae, result.mfe
    t.excursion_source = f"{name} 1m bid/ask"
    t.excursion_computed_at = utcnow()
    db.commit()
    return result


def excursions_out(t: Trade, result: ex.Excursions | None) -> dict | None:
    if t.mae is None or t.mfe is None:
        return None
    r = None
    if t.initial_risk and t.initial_risk > 0:
        q = Decimal("0.0001")
        r = {"mae_r": (t.mae / t.initial_risk).quantize(q), "mfe_r": (t.mfe / t.initial_risk).quantize(q)}
    out = {
        "mae": t.mae, "mfe": t.mfe, "source": t.excursion_source, "computed_at": t.excursion_computed_at,
        "r": r,
        "precision": "1-minute bars. Minutes containing a fill are evaluated at fill prices only.",
    }  # fmt: skip
    if result is not None:
        out |= {"mae_at": result.mae_at, "mfe_at": result.mfe_at, "minutes_missing": result.minutes_missing}
    return out


def build(db: Session, t: Trade, timeframe: str, side: str) -> dict:
    provider = get_provider()
    if provider is None:
        return unsupported("Historical market data is disabled on this server.", None)
    inst = db.get(Instrument, t.instrument_id)
    assert inst is not None
    symbol = provider.provider_symbol(inst.symbol, inst.asset_class)
    if symbol is None:
        return unsupported(
            f"{provider.info.display_name} covers {', '.join(provider.info.asset_classes)} only; "
            f"{inst.symbol} ({inst.asset_class}) has no candles yet.",
            provider,
        )
    now = utcnow()
    w = trade_window(t, timeframe, now)
    cov = md.ensure_range(db, provider, symbol, w.start, w.end)
    name = provider.info.name
    bars = md.load_bars(db, name, symbol, side, w.start, w.end, timeframe) if cov.status != "pending" else []
    minutes = md.load_minutes(db, name, symbol, "bid", w.start, w.end) if bars else []
    result = None
    if cov.status != "pending" and (t.mae is None or t.mfe is None):
        result = maybe_store_excursions(db, t, provider, symbol)
    fills = fill_points(db, t)
    return {
        "status": cov.status,
        "provider": provider_out(provider),
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "start": w.start,
        "end": w.end,
        "coverage": md.coverage_out(cov),
        "bars": [md.bar_out(b) for b in bars],
        "gaps": md.gaps_out(minutes, w.start, w.end) if minutes else [],
        "markers": [
            {
                "t": int(f.ts.timestamp()),
                "ts": f.ts,
                "side": "buy" if f.signed_qty > 0 else "sell",
                "quantity": abs(f.signed_qty),
                "price": f.price,
            }  # fmt: skip
            for f in fills
        ],
        "planned_stop_price": t.planned_stop_price,
        "planned_target_price": t.planned_target_price,
        "excursions": excursions_out(t, result),
        "notes": [
            f"Prices are {provider.info.display_name} {side} quotes. Your broker's prices can differ slightly.",
            "Candles are 1-minute data aggregated to the selected timeframe; there is no tick-level detail.",
        ],
    }

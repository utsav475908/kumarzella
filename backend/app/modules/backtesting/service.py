"""Backtest sessions: cursor moves, order placement, persisting simulator events, results and reproducibility."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.analytics import metrics as mx
from app.modules.backtesting import simulator as sim
from app.modules.backtesting.models import BacktestFill, BacktestOrder, BacktestSession, BacktestTrade
from app.modules.instruments.rules import entry_session, market_local_time, session_date
from app.modules.marketdata import service as md
from app.modules.positions import engine
from app.modules.replay import service as rp

SIZE_STEP = Decimal(1000)  # risk-based sizes are rounded down to 1,000 units (a micro lot)
MAX_QTY = Decimal(100_000_000)
QUOTE_LOOKBACK = timedelta(days=4)
DISCLAIMER = (
    "Simulated on historical 1-minute bid/ask candles. Fills follow fixed rules (see the configuration) and cannot "
    "reproduce real liquidity, partial fills or tick-level order of events. A profitable backtest is not evidence "
    "of future results."
)


def pip_size(symbol: str) -> Decimal:
    return Decimal("0.01") if symbol.endswith("JPY") else Decimal("0.0001")


def make_config(symbol: str, commission_per_100k: Decimal, slippage_pips: Decimal, provider: str) -> dict:
    return {
        "simulator": sim.SIM_VERSION,
        "provider": provider,
        "data": "1-minute bid and ask candles; buys fill on the ask, sells on the bid",
        "commission_per_100k": str(commission_per_100k),
        "commission_note": "per side, per 100,000 units of the base currency, in the quote currency",
        "slippage_pips": str(slippage_pips),
        "slippage_price": str(slippage_pips * pip_size(symbol)),
        "slippage_note": "added against the trader on market and stop fills; limit fills never slip",
        "partial_fills": False,
        "intrabar_rule": "orders crossed at the open first; otherwise stop-loss first and the minute marked ambiguous",
        "position_accounting": "average_cost",
    }


def config_of(bs: BacktestSession) -> sim.Config:
    return sim.Config(Decimal(bs.config["commission_per_100k"]), Decimal(bs.config["slippage_price"]))


def owned(db: Session, user_id: UUID, sid: UUID) -> BacktestSession:
    bs = db.get(BacktestSession, sid)
    if bs is None or bs.user_id != user_id:
        raise NotFound("Backtest session not found")
    return bs


def require_active(bs: BacktestSession) -> None:
    if bs.status != "active":
        raise Conflict("This session is finished")


def to_sim(o: BacktestOrder) -> sim.Order:
    return sim.Order(o.key, o.seq, o.kind, o.side, o.type, o.quantity, o.price, o.active_from, o.stop_loss,
                     o.take_profit, o.key.rsplit(":", 1)[0] if o.kind != "entry" else None, o.root_seq)  # fmt: skip


def orders(db: Session, bs: BacktestSession) -> list[BacktestOrder]:
    return list(db.scalars(select(BacktestOrder).where(BacktestOrder.session_id == bs.id).order_by(BacktestOrder.seq)))


def fills(db: Session, bs: BacktestSession) -> list[BacktestFill]:
    return list(db.scalars(select(BacktestFill).where(BacktestFill.session_id == bs.id).order_by(BacktestFill.seq)))


def position(db: Session, bs: BacktestSession) -> Decimal:
    rows = db.execute(select(BacktestFill.side, func.sum(BacktestFill.quantity)).where(BacktestFill.session_id == bs.id)
                      .group_by(BacktestFill.side)).all()  # fmt: skip
    return sum((q if side == "buy" else -q for side, q in rows), Decimal(0))


def minutes(db: Session, bs: BacktestSession, start: datetime, end: datetime) -> list[tuple]:
    bid = md.load_minutes(db, bs.provider, bs.symbol, "bid", start, end)
    ask = md.load_minutes(db, bs.provider, bs.symbol, "ask", start, end)
    return [(b, a) for b, a in sim.pair_minutes(bid, ask) if start <= b.ts < end]


def last_quote(db: Session, bs: BacktestSession):
    """The last fully revealed minute (bid bar, ask bar) before the cursor, or None."""
    m = minutes(db, bs, max(bs.start_at - QUOTE_LOOKBACK, bs.cursor_at - QUOTE_LOOKBACK), bs.cursor_at)
    return m[-1] if m else None


def simulate(db: Session, bs: BacktestSession, start: datetime, end: datetime) -> sim.Events:
    """Run the simulator over [start, end) from the stored state and persist what happened."""
    all_orders = orders(db, bs)
    pending = [o for o in all_orders if o.status == "pending"]
    total = sim.Events()
    if not pending or end <= start:
        return total
    by_key = {o.key: o for o in all_orders}
    state = sim.State(position=position(db, bs), pending=[to_sim(o) for o in pending], next_seq=bs.next_seq)
    fill_seq = (db.scalar(select(func.max(BacktestFill.seq)).where(BacktestFill.session_id == bs.id)) or 0) + 1
    cfg = config_of(bs)
    for bid, ask in minutes(db, bs, start, end):
        if not state.pending:
            break
        ev = sim.step(state, cfg, bid, ask)
        for c in ev.created:
            parent = by_key[c.parent or ""]
            row = BacktestOrder(id=uuid.uuid4(), session_id=bs.id, user_id=bs.user_id, key=c.key, seq=c.seq,
                                root_seq=c.root_seq, kind=c.kind, parent_id=parent.id, side=c.side, type=c.type,
                                quantity=c.quantity, price=c.price, placed_at=bid.ts, active_from=c.active_from,
                                status="pending")  # fmt: skip
            db.add(row)
            by_key[c.key] = row
        if ev.created:
            db.flush()  # a child can fill later in this run; its row must exist before the fill that points at it
        for f in ev.fills:
            o = by_key[f.order_key]
            o.status = "filled"
            db.add(BacktestFill(session_id=bs.id, user_id=bs.user_id, order_id=o.id, seq=fill_seq, ts=f.ts,
                                side=f.side, quantity=f.quantity, price=f.price, commission=f.commission,
                                slippage=f.slippage, ambiguous=f.ambiguous, reason=f.reason or None))  # fmt: skip
            fill_seq += 1
        for c in ev.cancels:
            o = by_key[c.order_key]
            o.status, o.cancelled_at, o.reason = "cancelled", c.ts, c.reason
        total.fills += ev.fills
        total.cancels += ev.cancels
        total.created += ev.created
    bs.next_seq = state.next_seq
    db.flush()
    if total.fills:
        rebuild_trades(db, bs)
    return total


def move_cursor(db: Session, bs: BacktestSession, new_cursor: datetime) -> sim.Events:
    old = bs.cursor_at
    bs.cursor_at = new_cursor
    return simulate(db, bs, old, new_cursor)


def advance(db: Session, bs: BacktestSession, steps: int) -> tuple[list, sim.Events]:
    require_active(bs)
    old = bs.cursor_at
    new = rp.advance(db, bs, steps)  # type: ignore[arg-type]  # same cursor rules as a blind replay
    ev = simulate(db, bs, old, bs.cursor_at)
    return new, ev


def place_order(db: Session, bs: BacktestSession, *, side: str, type_: str, quantity: Decimal | None,
                risk_amount: Decimal | None, price: Decimal | None, stop_loss: Decimal | None,
                take_profit: Decimal | None, note: str | None) -> BacktestOrder:  # fmt: skip
    require_active(bs)
    if bs.cursor_at >= bs.end_at:
        raise ValidationFailed("The session has reached its end; finish it to see the results", code="session_ended")
    if (type_ == "market") != (price is None):
        raise ValidationFailed("Market orders take no price; limit and stop orders need one", code="invalid_order")
    q = last_quote(db, bs)
    if q is None:
        raise ValidationFailed("No price has been revealed yet; advance the replay first", code="no_quote")
    bid, ask = q
    ref = price if price is not None else (ask.close if side == "buy" else bid.close)
    long = side == "buy"
    if stop_loss is not None and (stop_loss >= ref if long else stop_loss <= ref):
        raise ValidationFailed(f"The stop-loss must be {'below' if long else 'above'} the entry ({ref})",
                               code="invalid_bracket")  # fmt: skip
    if take_profit is not None and (take_profit <= ref if long else take_profit >= ref):
        raise ValidationFailed(f"The take-profit must be {'above' if long else 'below'} the entry ({ref})",
                               code="invalid_bracket")  # fmt: skip
    if (quantity is None) == (risk_amount is None):
        raise ValidationFailed("Give either a quantity or a risk amount", code="invalid_size")
    if risk_amount is not None:
        if stop_loss is None:
            raise ValidationFailed("Sizing by risk needs a stop-loss", code="invalid_size")
        quantity = (risk_amount / abs(ref - stop_loss) / SIZE_STEP).to_integral_value(ROUND_DOWN) * SIZE_STEP
        if quantity <= 0:
            raise ValidationFailed(f"That risk buys less than {SIZE_STEP:,} units at this stop distance",
                                   code="invalid_size")  # fmt: skip
    assert quantity is not None
    if quantity > MAX_QTY:
        raise ValidationFailed("Quantity is too large", code="invalid_size")
    seq = bs.next_seq
    bs.next_seq += 1
    o = BacktestOrder(id=uuid.uuid4(), session_id=bs.id, user_id=bs.user_id, key=f"o{seq}", seq=seq, root_seq=seq,
                      kind="entry", side=side, type=type_, quantity=quantity, price=price, stop_loss=stop_loss,
                      take_profit=take_profit, risk_amount=risk_amount, placed_at=bs.cursor_at,
                      active_from=bs.cursor_at, status="pending", note=note)  # fmt: skip
    db.add(o)
    db.flush()
    return o


def cancel_order(db: Session, bs: BacktestSession, oid: UUID) -> BacktestOrder:
    require_active(bs)
    o = db.get(BacktestOrder, oid)
    if o is None or o.session_id != bs.id:
        raise NotFound("Order not found")
    if o.status != "pending":
        raise Conflict(f"The order is already {o.status}")
    o.status, o.cancelled_at, o.cancelled_by_user, o.reason = "cancelled", bs.cursor_at, True, "cancelled by you"
    return o


def finish(db: Session, bs: BacktestSession, flatten: bool) -> BacktestFill | None:
    require_active(bs)
    out = None
    pos = position(db, bs)
    if flatten and pos != 0:
        q = last_quote(db, bs)
        assert q is not None  # a position exists, so bars were revealed
        st = sim.State(position=pos)
        f = sim.flatten(st, config_of(bs), q[0], q[1], bs.cursor_at, "finish")
        assert f is not None
        seq = (db.scalar(select(func.max(BacktestFill.seq)).where(BacktestFill.session_id == bs.id)) or 0) + 1
        out = BacktestFill(session_id=bs.id, user_id=bs.user_id, order_id=None, seq=seq, ts=f.ts, side=f.side,
                           quantity=f.quantity, price=f.price, commission=f.commission, slippage=f.slippage,
                           ambiguous=False, reason=f.reason)  # fmt: skip
        db.add(out)
    for o in orders(db, bs):
        if o.status == "pending":
            o.status, o.cancelled_at, o.reason = "cancelled", bs.cursor_at, "session finished"
    bs.status, bs.completed_at = "completed", utcnow()
    db.flush()
    rebuild_trades(db, bs)
    return out


def rebuild_trades(db: Session, bs: BacktestSession) -> None:
    fs = fills(db, bs)
    db.execute(delete(BacktestTrade).where(BacktestTrade.session_id == bs.id))
    if not fs:
        return
    by_id = {str(f.id): f for f in fs}
    stops = {o.id: o.stop_loss for o in orders(db, bs) if o.kind == "entry"}
    for n, rt in enumerate(_reconstruct(fs).trades, 1):
        first = by_id[rt.allocations[0].execution_id]
        stop = stops.get(first.order_id) if first.order_id else None
        risk = abs(rt.entry_avg_price - stop) * rt.peak_qty if stop is not None else None
        net = rt.net_pnl
        db.add(BacktestTrade(
            session_id=bs.id, user_id=bs.user_id, number=n, direction=rt.direction, status=rt.status,
            opened_at=rt.opened_at, closed_at=rt.closed_at, entry_qty=rt.entry_qty, peak_qty=rt.peak_qty,
            entry_avg_price=rt.entry_avg_price, exit_avg_price=rt.exit_avg_price, gross_pnl=rt.gross_pnl,
            fees=rt.fees, net_pnl=net, initial_risk=risk,
            r_multiple=(net / risk).quantize(mx.RATIO_Q) if risk and rt.status == "closed" else None,
            ambiguous=any(by_id[a.execution_id].ambiguous for a in rt.allocations),
        ))  # fmt: skip
    db.flush()


def trades(db: Session, bs: BacktestSession) -> list[BacktestTrade]:
    return list(db.scalars(select(BacktestTrade).where(BacktestTrade.session_id == bs.id)
                           .order_by(BacktestTrade.number)))  # fmt: skip


def _reconstruct(fs: list[BacktestFill]) -> engine.ReconstructionResult:
    return engine.reconstruct(
        [engine.Fill(str(f.id), f.side, f.quantity, f.price, f.commission, f.ts, f.seq, "simulated") for f in fs],
        Decimal(1),
    )


def open_pnl(db: Session, bs: BacktestSession) -> Decimal | None:
    """Gross P&L of the open trade (including any partial exits) marked at the last revealed close: bid for longs,
    ask for shorts. Same formula as MAE/MFE: position x mark - signed cash flow of the trade's fills."""
    pos = position(db, bs)
    q = last_quote(db, bs) if pos != 0 else None
    if q is None:
        return None
    fs = fills(db, bs)
    by_id = {str(f.id): f for f in fs}
    open_trade = _reconstruct(fs).trades[-1]
    cash = sum((-(a.quantity if by_id[a.execution_id].side == "buy" else -a.quantity) * by_id[a.execution_id].price
                for a in open_trade.allocations), Decimal(0))  # fmt: skip
    return mx.m(pos * (q[0].close if pos > 0 else q[1].close) + cash)


def results(db: Session, bs: BacktestSession) -> dict:
    ts = trades(db, bs)
    rows = [
        mx.TradeRow(
            id=t.id,
            account_id=bs.id,
            symbol=bs.symbol,
            asset_class="forex",
            direction=t.direction,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            session_date=session_date(t.closed_at, "forex"),
            entry_session=entry_session(t.opened_at, "forex"),
            entry_hour=market_local_time(t.opened_at, "forex").hour,
            gross_pnl=t.gross_pnl,
            fees=t.fees,
            net_pnl=t.net_pnl,
            holding_seconds=int((t.closed_at - t.opened_at).total_seconds()),
            initial_risk=t.initial_risk,
            r_multiple=t.r_multiple,
        )  # fmt: skip
        for t in ts
        if t.status == "closed" and t.closed_at is not None
    ]
    s = mx.summary(rows)
    curve, dd = mx.equity_curve(rows)
    realized = sum((r.net_pnl for r in rows), Decimal(0))
    fs = fills(db, bs)
    warnings = []
    if 0 < len(rows) < mx.SMALL_SAMPLE:
        n = len(rows)
        warnings.append(f"Small sample: {n} closed simulated trade{'' if n == 1 else 's'}. Treat ratios as unreliable.")
    amb = sum(1 for f in fs if f.ambiguous)
    if amb:
        warnings.append(f"{amb} fill(s) happened in a minute where the order of events is unknown; the simulator "
                        f"assumed the worse outcome. See the fills marked ambiguous.")  # fmt: skip
    return {
        "currency": bs.currency,
        "starting_balance": mx.m(bs.starting_balance),
        "realized_net_pnl": mx.m(realized),
        "balance": mx.m(bs.starting_balance + realized),
        "return_pct": mx.ratio(realized, bs.starting_balance),
        "position": position(db, bs),
        "open_pnl": open_pnl(db, bs),
        "summary": {**s, **dd, **mx.streaks(rows)},
        "equity_curve": curve,
        "ambiguous_fills": amb,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


def verify(db: Session, bs: BacktestSession) -> dict:
    """Re-run the session from its order log and the stored configuration and compare with the stored fills."""
    os_ = orders(db, bs)
    log = [sim.LoggedOrder(to_sim(o), o.placed_at, o.cancelled_at if o.cancelled_by_user else None)
           for o in os_ if o.kind == "entry"]  # fmt: skip
    kid_cancels = {o.key: o.cancelled_at for o in os_ if o.kind != "entry" and o.cancelled_by_user and o.cancelled_at}
    stored = fills(db, bs)
    keys = {o.id: o.key for o in os_}
    fin = next((f for f in stored if f.order_id is None), None)
    first = min((o.placed_at for o in os_), default=bs.cursor_at)
    rerun = sim.rerun(config_of(bs), log, kid_cancels, minutes(db, bs, first, bs.cursor_at),
                      finish=(fin.ts, "finish") if fin else None)  # fmt: skip

    def norm(key, ts, side, qty, px, com, amb):
        return (key, ts.isoformat(), side, format(qty.normalize(), "f"), format(px.normalize(), "f"),
                format(com.normalize(), "f"), amb)  # fmt: skip

    a = [norm(keys.get(f.order_id, "finish"), f.ts, f.side, f.quantity, f.price, f.commission, f.ambiguous)
         for f in stored]  # fmt: skip
    b = [norm(f.order_key, f.ts, f.side, f.quantity, f.price, f.commission, f.ambiguous) for f in rerun]
    return {"reproducible": a == b, "stored_fills": len(a), "rerun_fills": len(b), "simulator": bs.config["simulator"],
            "mismatches": [{"stored": x, "rerun": y} for x, y in zip(a, b, strict=False) if x != y][:5]}  # fmt: skip

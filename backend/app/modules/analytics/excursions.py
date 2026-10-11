"""Maximum adverse and favourable excursion (MAE / MFE) from 1-minute bid/ask bars. See docs/metrics.md.

Definition: the trade's open P&L at a moment is realized cash flow so far plus the open position marked to price:

    open_pnl(mark) = multiplier x (position x mark - sum(signed fill qty x fill price))

which does not depend on the accounting policy. MAE is the lowest open P&L reached while the trade was open
(capped at 0), MFE the highest (floored at 0). Both are gross: fees are excluded.

Marks: a long position can be closed at the bid, a short at the ask, so a long is marked at bid low (worst) and
bid high (best), a short at ask high (worst) and ask low (best).

Precision: with 1-minute bars, only minutes that lie wholly inside a period of constant position use the bar's
extremes. A minute that contains a fill is evaluated at the fill prices only, because the bar's high or low may
have happened before entry or after exit. Excursions inside fill minutes can therefore be understated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.money import ZERO, q8
from app.modules.marketdata.bars import bucket_start
from app.modules.marketdata.providers.base import Bar


@dataclass(frozen=True)
class FillPoint:
    ts: datetime
    signed_qty: Decimal  # + buy, - sell (the part allocated to this trade)
    price: Decimal


@dataclass(frozen=True)
class Excursions:
    mae: Decimal  # <= 0
    mfe: Decimal  # >= 0
    mae_at: datetime
    mfe_at: datetime
    minutes_evaluated: int
    minutes_missing: int


def compute(fills: list[FillPoint], multiplier: Decimal, bid: list[Bar], ask: list[Bar]) -> Excursions | None:
    """None when there are no fills or the trade is still open at the last fill."""
    if not fills:
        return None
    fills = sorted(fills, key=lambda f: f.ts)
    one = timedelta(minutes=1)
    bid_at = {b.ts: b for b in bid}
    ask_at = {a.ts: a for a in ask}

    pos = ZERO
    cost = ZERO  # sum(signed qty x price)
    worst = best = ZERO
    worst_at = best_at = fills[0].ts
    evaluated = missing = 0

    def pnl(mark: Decimal) -> Decimal:
        return multiplier * (pos * mark - cost)

    def consider(value: Decimal, ts: datetime) -> None:
        nonlocal worst, best, worst_at, best_at
        if value < worst:
            worst, worst_at = value, ts
        if value > best:
            best, best_at = value, ts

    i = 0
    while i < len(fills):
        minute = bucket_start(fills[i].ts, 60)
        # Apply every fill in this minute, marking at each fill price.
        while i < len(fills) and bucket_start(fills[i].ts, 60) == minute:
            f = fills[i]
            pos += f.signed_qty
            cost += f.signed_qty * f.price
            consider(pnl(f.price), f.ts)
            i += 1
        if pos == 0:
            if i < len(fills):
                continue
            break
        if i >= len(fills):
            return None  # still open after the last fill
        # Whole minutes strictly between this fill minute and the next fill minute: constant position.
        t = minute + one
        next_minute = bucket_start(fills[i].ts, 60)
        while t < next_minute:
            bar = bid_at.get(t) if pos > 0 else ask_at.get(t)
            if bar is None:
                missing += 1
            else:
                evaluated += 1
                lo, hi = pnl(bar.low), pnl(bar.high)
                consider(min(lo, hi), t)
                consider(max(lo, hi), t)
            t += one
    return Excursions(q8(worst), q8(best), worst_at, best_at, evaluated, missing)

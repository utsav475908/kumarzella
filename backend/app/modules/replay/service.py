"""Replay cursor rules.

A bar is revealed when its close time (start + timeframe) is at or before the session cursor. The cursor always
sits on a timeframe boundary, so a partially formed bar is never sent. In blind mode the server is the only place
that knows bars beyond the cursor; the client only ever receives revealed bars.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.marketdata import bars as bx
from app.modules.marketdata import service as md
from app.modules.marketdata.providers.base import Bar
from app.modules.replay.models import ReplaySession

WARMUP_BARS = 60
HORIZON = timedelta(days=4)  # covers a weekend when searching for the next bars


def tf(rs: ReplaySession) -> timedelta:
    return timedelta(seconds=bx.tf_seconds(rs.timeframe))


def align(ts: datetime, timeframe: str) -> datetime:
    return bx.bucket_start(ts, bx.tf_seconds(timeframe))


def revealed(rs: ReplaySession, bars: list[Bar]) -> list[Bar]:
    step = tf(rs)
    return [b for b in bars if b.ts + step <= rs.cursor_at]


def all_bars(db: Session, rs: ReplaySession) -> list[Bar]:
    return md.load_bars(db, rs.provider, rs.symbol, rs.side, rs.start_at, rs.end_at, rs.timeframe)


def bars_until_cursor(db: Session, rs: ReplaySession) -> list[Bar]:
    end = min(rs.cursor_at, rs.end_at)
    return revealed(rs, md.load_bars(db, rs.provider, rs.symbol, rs.side, rs.start_at, end, rs.timeframe))


def next_bars(db: Session, rs: ReplaySession, steps: int) -> list[Bar]:
    """The next `steps` complete bars after the cursor, skipping closed-market time."""
    out: list[Bar] = []
    t = rs.cursor_at
    step = tf(rs)
    while len(out) < steps and t < rs.end_at:
        until = min(t + HORIZON, rs.end_at)
        chunk = md.load_bars(db, rs.provider, rs.symbol, rs.side, t, until, rs.timeframe)
        complete = [b for b in chunk if b.ts >= t and b.ts + step <= until]
        out.extend(complete[: steps - len(out)])
        t = until
    return out


def advance(db: Session, rs: ReplaySession, steps: int) -> list[Bar]:
    new = next_bars(db, rs, steps)
    # Fewer bars than asked means the window has no more data: the replay is at its end.
    rs.cursor_at = rs.end_at if len(new) < steps else new[-1].ts + tf(rs)
    return new


def initial_cursor(db: Session, rs: ReplaySession) -> datetime:
    """Blind sessions open with up to WARMUP_BARS of context, never more than a quarter of the window; review
    sessions start at the window start."""
    if rs.mode == "review":
        return rs.start_at
    rs.cursor_at = rs.start_at
    limit = rs.start_at + (rs.end_at - rs.start_at) / 4
    warm = [b for b in next_bars(db, rs, WARMUP_BARS) if b.ts + tf(rs) <= limit]
    return warm[-1].ts + tf(rs) if warm else rs.start_at


def progress(rs: ReplaySession) -> float:
    total = (rs.end_at - rs.start_at).total_seconds()
    return round(min(1.0, max(0.0, (rs.cursor_at - rs.start_at).total_seconds() / total)), 4) if total else 1.0

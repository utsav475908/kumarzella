"""Pure bar helpers: timeframe aggregation, mid prices and gap detection. No I/O."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.modules.marketdata.providers.base import Bar

TIMEFRAMES: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
NY = ZoneInfo("America/New_York")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def tf_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise ValueError(f"Unsupported timeframe {timeframe!r}") from None


def bucket_start(ts: datetime, seconds: int) -> datetime:
    s = int((ts - EPOCH).total_seconds())
    return EPOCH + timedelta(seconds=s - s % seconds)


def aggregate(bars: Iterable[Bar], timeframe: str) -> list[Bar]:
    """Aggregate ascending 1-minute bars into UTC-aligned buckets (4h buckets start at 00, 04, 08 ... UTC)."""
    secs = tf_seconds(timeframe)
    if secs == 60:
        return list(bars)
    out: list[Bar] = []
    cur: Bar | None = None
    for b in bars:
        start = bucket_start(b.ts, secs)
        if cur is not None and cur.ts == start:
            cur = Bar(start, cur.open, max(cur.high, b.high), min(cur.low, b.low), b.close, cur.volume + b.volume)
        else:
            if cur is not None:
                out.append(cur)
            cur = Bar(start, b.open, b.high, b.low, b.close, b.volume)
    if cur is not None:
        out.append(cur)
    return out


def mid(bid: list[Bar], ask: list[Bar]) -> list[Bar]:
    """Approximate mid bars: the average of bid and ask OHLC for minutes present on both sides."""
    by_ts = {a.ts: a for a in ask}
    two = Decimal(2)
    out = []
    for b in bid:
        a = by_ts.get(b.ts)
        if a is None:
            continue
        out.append(
            Bar(b.ts, (b.open + a.open) / two, (b.high + a.high) / two, (b.low + a.low) / two,
                (b.close + a.close) / two, b.volume + a.volume)
        )  # fmt: skip
    return out


def forex_open(ts: datetime) -> bool:
    """Forex trades from Sunday 17:00 to Friday 17:00 New York time (holidays not modelled)."""
    local = ts.astimezone(NY)
    wd, t = local.weekday(), local.time()
    if wd == 5:
        return False
    if wd == 6:
        return t >= time(17, 0)
    if wd == 4:
        return t < time(17, 0)
    return True


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime  # exclusive
    minutes: int


def find_gaps(bars: list[Bar], start: datetime, end: datetime, min_minutes: int = 5) -> list[Gap]:
    """Runs of at least min_minutes consecutive market-open minutes in [start, end) without a 1-minute bar.

    A gap means the provider recorded no ticks; around the 17:00 New York rollover this is normal.
    """
    have = {b.ts for b in bars}
    gaps: list[Gap] = []
    t = bucket_start(start, 60)
    run_start: datetime | None = None
    one = timedelta(minutes=1)
    while t < end:
        missing = forex_open(t) and t not in have
        if missing and run_start is None:
            run_start = t
        elif not missing and run_start is not None:
            n = int((t - run_start) / one)
            if n >= min_minutes:
                gaps.append(Gap(run_start, t, n))
            run_start = None
        t += one
    if run_start is not None:
        n = int((t - run_start) / one)
        if n >= min_minutes:
            gaps.append(Gap(run_start, t, n))
    return gaps

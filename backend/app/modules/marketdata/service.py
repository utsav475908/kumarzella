"""Market-data cache: fetch provider days on demand, store 1-minute bars, track coverage, serve bars and gaps.

Bars are cached per (provider, symbol, UTC day). A day is fetched once and then served from PostgreSQL; failed
days are retried after marketdata_error_retry_minutes. Ranges that need many uncached days are handed to the
Celery worker so API requests stay short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.logging import log
from app.modules.marketdata import bars as bx
from app.modules.marketdata.models import Candle, CandleCoverage
from app.modules.marketdata.providers.base import Bar, MarketDataProvider, ProviderError

QUEUED_STALE = timedelta(minutes=10)
MAX_RANGE_DAYS = 31
MAX_BARS = 20_000


@dataclass
class Coverage:
    """Availability of a requested range. status: ready | pending | partial | unavailable."""

    status: str
    pending_days: list[date] = field(default_factory=list)
    failed: dict[date, str] = field(default_factory=dict)
    unpublished_days: list[date] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.status == "ready"


def utc_days(start: datetime, end: datetime) -> list[date]:
    d, last = start.astimezone(UTC).date(), (end - timedelta(microseconds=1)).astimezone(UTC).date()
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def _needs_fetch(c: CandleCoverage | None, now: datetime) -> bool:
    s = get_settings()
    if c is None:
        return True
    if c.status == "error":
        return now - c.updated_at >= timedelta(minutes=s.marketdata_error_retry_minutes)
    if c.status == "queued":
        return now - c.updated_at >= QUEUED_STALE
    return False


def _coverage(db: Session, provider: str, symbol: str, days: list[date]) -> dict[date, CandleCoverage]:
    if not days:
        return {}
    rows = db.scalars(
        select(CandleCoverage)
        .where(CandleCoverage.provider == provider, CandleCoverage.symbol == symbol, CandleCoverage.day.in_(days))
        .execution_options(populate_existing=True)  # rows are upserted with Core statements
    )
    return {c.day: c for c in rows}


def _set_coverage(db: Session, provider: str, symbol: str, day: date, status: str, bar_count: int = 0,
                  error: str | None = None) -> None:  # fmt: skip
    values = {"provider": provider, "symbol": symbol, "day": day, "status": status, "bar_count": bar_count,
                  "updated_at": utcnow(), "error": error}  # fmt: skip
    stmt = insert(CandleCoverage).values(**values)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["provider", "symbol", "day"],
            set_={k: stmt.excluded[k] for k in ("status", "bar_count", "updated_at", "error")},
        )
    )


def fetch_days(db: Session, provider: MarketDataProvider, symbol: str, days: list[date]) -> dict[date, str]:
    """Download and store each day (both quote sides). Commits per day. Returns {day: error} for failures."""
    name = provider.info.name
    failed: dict[date, str] = {}
    for day in days:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"md:{name}:{symbol}:{day}"})
        c = db.get(CandleCoverage, (name, symbol, day), populate_existing=True)
        if c is not None and c.status == "complete":
            db.commit()
            continue
        try:
            sides = {side: provider.fetch_day(symbol, day, side) for side in ("bid", "ask")}
        except ProviderError as e:
            msg = str(e)[:500]
            log.warning("marketdata_fetch_failed", provider=name, symbol=symbol, day=str(day), error=msg)
            _set_coverage(db, name, symbol, day, "error", error=msg)
            db.commit()
            failed[day] = msg
            continue
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        db.execute(
            delete(Candle).where(
                Candle.provider == name, Candle.symbol == symbol,
                Candle.ts >= start, Candle.ts < start + timedelta(days=1),
            )
        )  # fmt: skip
        rows = [
            {
                "provider": name,
                "symbol": symbol,
                "side": side,
                "ts": b.ts,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }  # fmt: skip
            for side, bars in sides.items()
            for b in bars
        ]
        for i in range(0, len(rows), 2000):
            db.execute(insert(Candle).values(rows[i : i + 2000]).on_conflict_do_nothing())
        _set_coverage(db, name, symbol, day, "complete", bar_count=len(sides["bid"]))
        db.commit()
        log.info("marketdata_day_cached", provider=name, symbol=symbol, day=str(day), bars=len(sides["bid"]))
    return failed


def ensure_range(db: Session, provider: MarketDataProvider, symbol: str, start: datetime, end: datetime) -> Coverage:
    """Make the range available: fetch missing days inline when few, otherwise queue them for the worker."""
    s = get_settings()
    now = utcnow()
    days = utc_days(start, end)
    today = now.date()
    published = [d for d in days if d < today]
    unpublished = [d for d in days if d >= today]
    name = provider.info.name
    cov = _coverage(db, name, symbol, published)
    need = [d for d in published if _needs_fetch(cov.get(d), now)]
    if need:
        if s.jobs_eager or len(need) <= s.marketdata_inline_max_days:
            fetch_days(db, provider, symbol, need)
        else:
            for d in need:
                _set_coverage(db, name, symbol, d, "queued")
            db.commit()
            from app.worker import fetch_marketdata_task

            fetch_marketdata_task.delay(name, symbol, [d.isoformat() for d in need])
        cov = _coverage(db, name, symbol, published)
    pending = [d for d in published if cov.get(d) is None or cov[d].status == "queued"]
    failed = {d: (cov[d].error or "fetch failed") for d in published if d in cov and cov[d].status == "error"}
    if pending:
        status = "pending"
    elif failed or unpublished:
        status = "partial" if len(failed) + len(unpublished) < len(days) else "unavailable"
    else:
        status = "ready"
    return Coverage(status, pending, failed, unpublished)


def load_minutes(db: Session, provider: str, symbol: str, side: str, start: datetime, end: datetime) -> list[Bar]:
    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close, Candle.volume)
        .where(
            Candle.provider == provider, Candle.symbol == symbol, Candle.side == side,
            Candle.ts >= bx.bucket_start(start, 60), Candle.ts < end,
        )
        .order_by(Candle.ts)
    ).all()  # fmt: skip
    return [Bar(*r) for r in rows]


def load_bars(db: Session, provider: str, symbol: str, side: str, start: datetime, end: datetime,
              timeframe: str) -> list[Bar]:  # fmt: skip
    if side == "mid":
        minutes = bx.mid(
            load_minutes(db, provider, symbol, "bid", start, end), load_minutes(db, provider, symbol, "ask", start, end)
        )
    else:
        minutes = load_minutes(db, provider, symbol, side, start, end)
    return bx.aggregate(minutes, timeframe)


def bar_out(b: Bar) -> dict:
    return {"t": int(b.ts.timestamp()), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}


def coverage_out(c: Coverage) -> dict:
    return {
        "status": c.status,
        "pending_days": [d.isoformat() for d in c.pending_days],
        "failed_days": [{"day": d.isoformat(), "error": e} for d, e in sorted(c.failed.items())],
        "unpublished_days": [d.isoformat() for d in c.unpublished_days],
    }


def gaps_out(minutes: list[Bar], start: datetime, end: datetime) -> list[dict]:
    return [
        {"start": g.start.isoformat(), "end": g.end.isoformat(), "minutes": g.minutes}
        for g in bx.find_gaps(minutes, start, end)
    ]

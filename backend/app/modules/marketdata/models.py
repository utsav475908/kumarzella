from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import Price, Qty


class Candle(Base):
    """One provider 1-minute bar. Shared reference data (not user-owned); higher timeframes are aggregated on read.

    ts is the bar's open time in UTC. side is the quote side the bar was built from ("bid" or "ask").
    """

    __tablename__ = "market_candles"
    __table_args__ = (CheckConstraint("side in ('bid','ask')", name="side"),)

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    side: Mapped[str] = mapped_column(String(3), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price, nullable=False)
    high: Mapped[Decimal] = mapped_column(Price, nullable=False)
    low: Mapped[Decimal] = mapped_column(Price, nullable=False)
    close: Mapped[Decimal] = mapped_column(Price, nullable=False)
    volume: Mapped[Decimal] = mapped_column(Qty, nullable=False)


class CandleCoverage(Base):
    """Which UTC days have been fetched for a provider symbol. This is the cache index.

    status: complete (both sides stored; zero bars means the market was closed), error (retry later),
    queued (a worker job is fetching it).
    """

    __tablename__ = "market_data_coverage"
    __table_args__ = (CheckConstraint("status in ('complete','error','queued')", name="status"),)

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    bar_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

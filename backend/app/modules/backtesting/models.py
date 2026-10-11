"""Manual backtesting. Simulated records live only in these tables and never mix with real trades or executions."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow
from app.core.types import Money, Price, Qty


class BacktestSession(IdMixin, TimestampMixin, Base):
    """A blind historical session the trader steps through while placing simulated orders.

    `config` is the exact simulation configuration (simulator version, costs, data source) so a session can be
    re-run and checked. Bars are revealed with the same rules as a blind replay: never a bar closing after the cursor.
    """

    __tablename__ = "backtest_sessions"
    __table_args__ = (
        CheckConstraint("status in ('active','completed')", name="status"),
        CheckConstraint("start_at < end_at and cursor_at >= start_at and cursor_at <= end_at", name="window"),
        CheckConstraint("starting_balance > 0", name="balance"),
        CheckConstraint("speed between 1 and 64", name="speed"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    side: Mapped[str] = mapped_column(String(3), default="bid", nullable=False)  # chart side; fills use bid and ask
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cursor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    speed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # quote currency of the pair
    starting_balance: Mapped[Decimal] = mapped_column(Money, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    mode = "blind"  # the replay cursor helpers treat a backtest as a blind replay


class BacktestOrder(IdMixin, Base):
    __tablename__ = "backtest_orders"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        UniqueConstraint("session_id", "key"),
        CheckConstraint("kind in ('entry','stop_loss','take_profit')", name="kind"),
        CheckConstraint("side in ('buy','sell')", name="side"),
        CheckConstraint("type in ('market','limit','stop')", name="type"),
        CheckConstraint("status in ('pending','filled','cancelled')", name="status"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("(type = 'market') = (price is null)", name="price"),
    )

    session_id: Mapped[UUID] = mapped_column(ForeignKey("backtest_sessions.id", ondelete="CASCADE"), index=True,
                                             nullable=False)  # fmt: skip
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    root_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("backtest_orders.id", ondelete="CASCADE"))
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    type: Mapped[str] = mapped_column(String(6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Price)
    stop_loss: Mapped[Decimal | None] = mapped_column(Price)
    take_profit: Mapped[Decimal | None] = mapped_column(Price)
    risk_amount: Mapped[Decimal | None] = mapped_column(Money)  # when the size came from a risk amount
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # session time
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BacktestFill(IdMixin, Base):
    __tablename__ = "backtest_fills"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)

    session_id: Mapped[UUID] = mapped_column(ForeignKey("backtest_sessions.id", ondelete="CASCADE"), index=True,
                                             nullable=False)  # fmt: skip
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("backtest_orders.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    commission: Mapped[Decimal] = mapped_column(Money, nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Price, nullable=False)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class BacktestTrade(IdMixin, Base):
    """Round trips rebuilt from the session's fills with the same position engine as real trades."""

    __tablename__ = "backtest_trades"

    session_id: Mapped[UUID] = mapped_column(ForeignKey("backtest_sessions.id", ondelete="CASCADE"), index=True,
                                             nullable=False)  # fmt: skip
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(String(6), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    peak_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    entry_avg_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    exit_avg_price: Mapped[Decimal | None] = mapped_column(Price)
    gross_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False)
    fees: Mapped[Decimal] = mapped_column(Money, nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False)
    initial_risk: Mapped[Decimal | None] = mapped_column(Money)
    r_multiple: Mapped[Decimal | None] = mapped_column(Money)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

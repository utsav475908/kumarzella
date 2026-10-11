from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.core.types import Money, Price, Qty


class Trade(IdMixin, TimestampMixin, Base):
    """A position lifecycle from flat to flat, reconstructed from executions.

    Calculated fields (prices, P&L, risk) are written only by the reconstruction service
    (app.modules.trades.reconstruction). Journal fields (stop, target, playbook, plan adherence)
    are user-editable and survive re-reconstruction because trades are keyed by their anchor execution.
    """

    __tablename__ = "trades"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "user_id"], ["accounts.id", "accounts.user_id"], ondelete="CASCADE"),
        CheckConstraint("direction in ('long','short')", name="direction"),
        CheckConstraint("status in ('open','closed')", name="status"),
        CheckConstraint("origin in ('imported','manual','mixed')", name="origin"),
        CheckConstraint("entry_session in ('regular','extended')", name="entry_session"),
        UniqueConstraint("anchor_execution_id", "anchor_leg"),
        UniqueConstraint("id", "user_id", name="uq_trades_id_user"),
        Index("ix_trades_user_session_date", "user_id", "session_date"),
        Index("ix_trades_account_instrument_opened", "account_id", "instrument_id", "opened_at"),
    )

    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    # Stable identity: the execution that opened the trade. anchor_leg=1 marks the opening remainder
    # of a reversal fill (the same execution also closed the previous trade).
    anchor_execution_id: Mapped[UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), nullable=False)
    anchor_leg: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_date: Mapped[date] = mapped_column(Date, nullable=False)  # exit session date (entry if open)
    entry_session: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    exit_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    peak_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    open_qty: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    entry_avg_price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    exit_avg_price: Mapped[Decimal | None] = mapped_column(Price)
    gross_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False)  # realized
    fees: Mapped[Decimal] = mapped_column(Money, nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False)  # realized gross - fees
    holding_seconds: Mapped[int | None] = mapped_column(Integer)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Planned risk (journal metadata, user-entered)
    planned_stop_price: Mapped[Decimal | None] = mapped_column(Price)
    planned_target_price: Mapped[Decimal | None] = mapped_column(Price)
    planned_risk_amount: Mapped[Decimal | None] = mapped_column(Money)
    # Derived from the above by the reconstruction service
    initial_risk: Mapped[Decimal | None] = mapped_column(Money)
    r_multiple: Mapped[Decimal | None] = mapped_column(Money)

    # Excursions from historical market data (app.modules.analytics.excursions). Cleared when fills change.
    mae: Mapped[Decimal | None] = mapped_column(Money)
    mfe: Mapped[Decimal | None] = mapped_column(Money)
    excursion_source: Mapped[str | None] = mapped_column(String(64))
    excursion_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    playbook_id: Mapped[UUID | None] = mapped_column(ForeignKey("playbooks.id", ondelete="SET NULL"), index=True)
    followed_plan: Mapped[bool | None] = mapped_column(Boolean)
    rating: Mapped[int | None] = mapped_column(Integer)


class TradeExecution(Base):
    """Allocation of an execution (or part of one, for reversals) to a trade."""

    __tablename__ = "trade_executions"
    __table_args__ = (
        CheckConstraint("role in ('open','add','reduce','close')", name="role"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    trade_id: Mapped[UUID] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    fees_allocated: Mapped[Decimal] = mapped_column(Money, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Money, nullable=False)
    position_after: Mapped[Decimal] = mapped_column(Qty, nullable=False)  # signed


class Position(IdMixin, Base):
    """Current open position per account and instrument, maintained by reconstruction."""

    __tablename__ = "positions"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "user_id"], ["accounts.id", "accounts.user_id"], ondelete="CASCADE"),
        UniqueConstraint("account_id", "instrument_id"),
    )

    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)  # signed
    avg_cost: Mapped[Decimal | None] = mapped_column(Price)
    open_trade_id: Mapped[UUID | None] = mapped_column(ForeignKey("trades.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.core.types import Money

ACCOUNTING_POLICIES = ("average_cost", "fifo")


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        # Target for composite ownership foreign keys from child tables.
        UniqueConstraint("id", "user_id", name="uq_accounts_id_user"),
        CheckConstraint("account_type in ('live','paper','demo')", name="account_type"),
        CheckConstraint("accounting_policy in ('average_cost','fifo')", name="accounting_policy"),
        CheckConstraint("char_length(base_currency) = 3", name="currency"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    broker: Mapped[str | None] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(16), default="live", nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", nullable=False)
    accounting_policy: Mapped[str] = mapped_column(String(16), default="average_cost", nullable=False)
    starting_balance: Mapped[Decimal | None] = mapped_column(Money)
    max_risk_per_trade: Mapped[Decimal | None] = mapped_column(Money)
    daily_loss_limit: Mapped[Decimal | None] = mapped_column(Money)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CashTransaction(IdMixin, TimestampMixin, Base):
    """Deposits and withdrawals. Kept separate from trading P&L by design."""

    __tablename__ = "cash_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"], ["accounts.id", "accounts.user_id"], ondelete="CASCADE"
        ),
        CheckConstraint("kind in ('deposit','withdrawal')", name="kind"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

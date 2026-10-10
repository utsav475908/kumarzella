from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.core.types import Money, Price, Qty


class Execution(IdMixin, TimestampMixin, Base):
    """A single normalized fill. Source of truth for every trade calculation."""

    __tablename__ = "executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"], ["accounts.id", "accounts.user_id"], ondelete="CASCADE"
        ),
        CheckConstraint("side in ('buy','sell')", name="side"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint("commission >= 0 and fees >= 0", name="costs_nonnegative"),
        CheckConstraint("source in ('import','manual','broker_sync')", name="source"),
        UniqueConstraint("account_id", "fingerprint"),
        Index(
            "uq_executions_account_source_id",
            "account_id",
            "source_execution_id",
            unique=True,
            postgresql_where=text("source_execution_id IS NOT NULL"),
        ),
        Index("ix_executions_account_instrument_time", "account_id", "instrument_id", "executed_at"),
        UniqueConstraint("id", "user_id", name="uq_executions_id_user"),
    )

    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    import_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"))
    raw_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "raw_import_records.id", ondelete="SET NULL", use_alter=True, name="fk_executions_raw_record"
        )
    )
    source_execution_id: Mapped[str | None] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    commission: Mapped[Decimal] = mapped_column(Money, default=Decimal(0), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Money, default=Decimal(0), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB)

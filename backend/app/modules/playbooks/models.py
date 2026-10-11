from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow
from app.core.types import Money


class Playbook(IdMixin, TimestampMixin, Base):
    """A strategy. Its rules live in immutable PlaybookVersion rows; editing the rules creates a new version, so a
    trade is always judged against the rules that were current when it was assigned."""

    __tablename__ = "playbooks"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlaybookVersion(IdMixin, Base):
    """One immutable revision of a playbook's rules.

    Machine-checkable limits (instruments, sessions, entry hours, stop required, max risk, minimum planned
    reward:risk, max trades per day) are verified from trade data. Everything that needs chart inspection or the
    trader's judgment is a checklist item the trader confirms; the two are always reported separately.
    """

    __tablename__ = "playbook_versions"
    __table_args__ = (
        UniqueConstraint("playbook_id", "version"),
        CheckConstraint("entry_hour_start is null or (entry_hour_start between 0 and 23)", name="hour_start"),
        CheckConstraint("entry_hour_end is null or (entry_hour_end between 1 and 24)", name="hour_end"),
        CheckConstraint("max_trades_per_day is null or max_trades_per_day > 0", name="max_trades"),
    )

    playbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Scope
    instruments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # symbols; empty = any
    timeframe: Mapped[str | None] = mapped_column(String(32))
    permitted_sessions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # regular/extended
    entry_hour_start: Mapped[int | None] = mapped_column(Integer)  # market-time hour window [start, end)
    entry_hour_end: Mapped[int | None] = mapped_column(Integer)
    # Written rules
    entry_rules: Mapped[str | None] = mapped_column(Text)
    exit_rules: Mapped[str | None] = mapped_column(Text)
    stop_rules: Mapped[str | None] = mapped_column(Text)
    target_rules: Mapped[str | None] = mapped_column(Text)
    sizing_rules: Mapped[str | None] = mapped_column(Text)
    invalidation: Mapped[str | None] = mapped_column(Text)
    valid_examples: Mapped[str | None] = mapped_column(Text)
    invalid_examples: Mapped[str | None] = mapped_column(Text)
    # Verifiable limits
    require_stop: Mapped[bool] = mapped_column(default=False, nullable=False)
    max_risk_per_trade: Mapped[Decimal | None] = mapped_column(Money)
    min_reward_risk: Mapped[Decimal | None] = mapped_column(Money)
    max_trades_per_day: Mapped[int | None] = mapped_column(Integer)
    # Checklists: [{"id": "p1", "text": "..."}]
    pre_trade_checklist: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    post_trade_checklist: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class TradeChecklistAnswer(Base):
    """The trader's answer to one checklist item for one trade (a self-assessment, never a verified fact)."""

    __tablename__ = "trade_checklist_answers"
    __table_args__ = (CheckConstraint("phase in ('pre','post')", name="phase"),)

    trade_id: Mapped[UUID] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    playbook_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbook_versions.id", ondelete="CASCADE"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(4), nullable=False)
    answer: Mapped[bool] = mapped_column(nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

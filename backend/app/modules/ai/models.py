"""AI coach reviews and the evidence behind them.

Every answer the coach gives is stored with the exact tool results it was allowed to use, so any figure in an answer
can be traced back to the analytics call that produced it.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, ForeignKeyConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin

REVIEW_KINDS = ("ask", "trade_review", "period_summary")
REVIEW_STATUSES = ("ok", "ungrounded", "declined", "incomplete")


class AiReview(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_reviews"
    __table_args__ = (
        CheckConstraint("kind in ('ask','trade_review','period_summary')", name="kind"),
        CheckConstraint("status in ('ok','ungrounded','declined','incomplete')", name="status"),
        # A review of a trade can only point at a trade of the same user, and goes away with it.
        ForeignKeyConstraint(["trade_id", "user_id"], ["trades.id", "trades.user_id"], ondelete="CASCADE"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_id: Mapped[UUID | None] = mapped_column(index=True)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    limitations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    suggested_tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    cited: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)  # evidence refs the answer cites
    unsupported_numbers: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    usage: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # tokens, tool calls, latency


class AiEvidence(IdMixin, TimestampMixin, Base):
    """One tool call the coach made: what it asked for and exactly what it got back."""

    __tablename__ = "ai_evidence"

    review_id: Mapped[UUID] = mapped_column(ForeignKey("ai_reviews.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ref: Mapped[str] = mapped_column(String(8), nullable=False)  # "E1", "E2", ...
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)

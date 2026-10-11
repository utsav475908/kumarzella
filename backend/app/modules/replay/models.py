from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow
from app.core.types import Price


class ReplaySession(IdMixin, TimestampMixin, Base):
    """A saved replay. review: retrospective look at a real trade, every bar visible. blind: bars are revealed
    one by one from the server and never sent before the cursor passes them."""

    __tablename__ = "replay_sessions"
    __table_args__ = (
        CheckConstraint("mode in ('review','blind')", name="mode"),
        CheckConstraint("side in ('bid','ask','mid')", name="side"),
        CheckConstraint("speed between 1 and 64", name="speed"),
        CheckConstraint("mode = 'review' or trade_id is null", name="blind_has_no_trade"),
        CheckConstraint("start_at < end_at and cursor_at >= start_at and cursor_at <= end_at", name="window"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    trade_id: Mapped[UUID | None] = mapped_column(ForeignKey("trades.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    side: Mapped[str] = mapped_column(String(3), default="bid", nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Close time of the last revealed bar. Bars whose close time is after the cursor are hidden in blind mode.
    cursor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    speed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # bars per second
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReplayAnnotation(IdMixin, Base):
    __tablename__ = "replay_annotations"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("replay_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Price)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

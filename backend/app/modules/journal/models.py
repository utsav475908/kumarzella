from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin

TAG_CATEGORIES = ("general", "setup", "mistake", "emotion")


class Tag(IdMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("id", "user_id", name="uq_tags_id_user"),
        CheckConstraint("category in ('general','setup','mistake','emotion')", name="category"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), default="general", nullable=False)
    color: Mapped[str | None] = mapped_column(String(16))


class TradeTag(Base):
    __tablename__ = "trade_tags"
    # Composite FKs guarantee a user can only attach their own tags to their own trades.
    __table_args__ = (
        ForeignKeyConstraint(["trade_id", "user_id"], ["trades.id", "trades.user_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tag_id", "user_id"], ["tags.id", "tags.user_id"], ondelete="CASCADE"),
    )

    trade_id: Mapped[UUID] = mapped_column(primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[UUID] = mapped_column(nullable=False)


class TradeNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "trade_notes"
    __table_args__ = (
        ForeignKeyConstraint(["trade_id", "user_id"], ["trades.id", "trades.user_id"], ondelete="CASCADE"),
    )

    trade_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class DayNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "day_notes"
    __table_args__ = (UniqueConstraint("user_id", "day"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

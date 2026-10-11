from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Attachment(IdMixin, TimestampMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(["trade_id", "user_id"], ["trades.id", "trades.user_id"], ondelete="CASCADE"),
        CheckConstraint("num_nonnulls(trade_id, playbook_id, backtest_session_id) = 1", name="one_owner"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    trade_id: Mapped[UUID | None] = mapped_column(index=True)
    # Playbook screenshots (setup examples). Exactly one owner column is set.
    playbook_id: Mapped[UUID | None] = mapped_column(ForeignKey("playbooks.id", ondelete="CASCADE"), index=True)
    # Backtest session screenshots. Simulated work never attaches to a real trade.
    backtest_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("backtest_sessions.id", ondelete="CASCADE"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

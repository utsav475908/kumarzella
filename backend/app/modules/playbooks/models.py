from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Playbook(IdMixin, TimestampMixin, Base):
    """Strategy playbook. Phase 3 stores name/description for strategy attribution;
    versioned rules and checklists arrive in Phase 4 (playbook_versions)."""

    __tablename__ = "playbooks"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

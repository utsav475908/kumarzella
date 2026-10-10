from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin

IMPORT_STATUSES = ("uploaded", "previewed", "queued", "committing", "completed", "failed")
RECORD_STATUSES = ("valid", "rejected", "duplicate", "imported")


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id"], ["accounts.id", "accounts.user_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "status in ('uploaded','previewed','queued','committing','completed','failed')", name="status"
        ),
        Index("ix_import_jobs_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", nullable=False)
    headers: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    mapping: Mapped[dict | None] = mapped_column(JSONB)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawImportRecord(IdMixin, Base):
    """Every CSV row exactly as received, plus its validation outcome. Retained for audit and reconciliation."""

    __tablename__ = "raw_import_records"
    __table_args__ = (
        UniqueConstraint("import_job_id", "row_number"),
        CheckConstraint("status in ('valid','rejected','duplicate','imported')", name="status"),
    )

    import_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based, excluding header
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    errors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL")
    )

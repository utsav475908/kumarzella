from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.core.types import Price, Qty

ASSET_CLASSES = ("stock", "etf", "option", "future", "forex", "crypto")


class Instrument(IdMixin, TimestampMixin, Base):
    """Shared reference data (not user-owned)."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("symbol", "asset_class"),
        CheckConstraint("asset_class in ('stock','etf','option','future','forex','crypto')", name="asset_class"),
        CheckConstraint("multiplier > 0", name="multiplier_positive"),
    )

    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Qty, default=Decimal(1), nullable=False)
    tick_size: Mapped[Decimal | None] = mapped_column(Price)
    root_symbol: Mapped[str | None] = mapped_column(String(32))
    underlying: Mapped[str | None] = mapped_column(String(32))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[Decimal | None] = mapped_column(Price)
    option_type: Mapped[str | None] = mapped_column(String(4))
    exchange: Mapped[str | None] = mapped_column(String(32))

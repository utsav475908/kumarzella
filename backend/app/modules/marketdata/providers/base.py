"""Provider-independent market-data interface. Adapters return 1-minute bars for one UTC day and one quote side."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Bar:
    ts: datetime  # bar open, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    display_name: str
    asset_classes: tuple[str, ...]
    granularity: str
    sides: tuple[str, ...]
    attribution: str
    licence_note: str
    volume_note: str


class ProviderError(Exception):
    """The provider answered but the data could not be used (corrupt file, unexpected layout)."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached (network, timeout, 5xx, rate limit). Retried later."""


class MarketDataProvider(Protocol):
    info: ProviderInfo

    def provider_symbol(self, symbol: str, asset_class: str) -> str | None:
        """The provider's symbol for an EdgeLedger instrument, or None when the instrument is not supported."""

    def fetch_day(self, provider_symbol: str, day: date, side: str) -> list[Bar]:
        """All 1-minute bars of one UTC day. An empty list means no trading (weekend, holiday)."""

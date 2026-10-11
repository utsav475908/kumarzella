"""Dukascopy historical forex candles.

Dukascopy publishes LZMA-compressed binary files ("bi5") per instrument, UTC day and quote side:

    {base}/{SYMBOL}/{YYYY}/{MM}/{DD}/{BID|ASK}_candles_min_1.bi5     (MM is zero-based: January = 00)

Each decompressed file is a sequence of 24-byte big-endian records, one per minute of the UTC day:

    uint32 seconds since 00:00 UTC, uint32 open, uint32 close, uint32 low, uint32 high, float32 volume

Prices are integers in units of 10^-5 (10^-3 for JPY-quoted pairs). Minutes without ticks are written as flat
bars with zero volume; those are dropped so they are not mistaken for prices. A missing or empty file means the
market was closed that day. Files exist only for completed UTC days.

Licence: the datafeed is published by Dukascopy Bank SA. Its download tools describe the data as for personal
use. EdgeLedger fetches it per user, for that user's own trades and replays; commercial display to end users
needs Dukascopy's written permission. See docs/security-and-compliance.md.
"""

from __future__ import annotations

import lzma
import struct
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.modules.marketdata.providers.base import Bar, ProviderError, ProviderInfo, ProviderUnavailable

RECORD = struct.Struct(">IIIIIf")
VOLUME_Q = Decimal("0.000001")

# Pairs this adapter is known to support. Quantities are base-currency units; prices are quote currency.
PAIRS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "AUDJPY", "CHFJPY", "CADJPY", "NZDJPY",
    "EURAUD", "EURCAD", "EURNZD", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDNZD", "AUDCAD", "AUDCHF", "CADCHF", "NZDCAD", "NZDCHF",
)  # fmt: skip

INFO = ProviderInfo(
    name="dukascopy",
    display_name="Dukascopy",
    asset_classes=("forex",),
    granularity="1-minute candles",
    sides=("bid", "ask"),
    attribution="Historical prices: Dukascopy Bank SA",
    licence_note=(
        "Dukascopy publishes this data for personal use. Each user's charts are fetched for their own trades. "
        "Displaying it commercially to end users needs Dukascopy's written permission."
    ),
    volume_note="Dukascopy volume reflects Dukascopy's own liquidity, not total market volume.",
)


def price_scale(symbol: str) -> Decimal:
    return Decimal(1000) if symbol.endswith("JPY") else Decimal(100000)


def day_path(symbol: str, day: date, side: str) -> str:
    return f"{symbol}/{day.year:04d}/{day.month - 1:02d}/{day.day:02d}/{side.upper()}_candles_min_1.bi5"


def decode_candles(raw: bytes, day: date, scale: Decimal) -> list[Bar]:
    if not raw:
        return []
    try:
        data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as e:
        raise ProviderError(f"Corrupt candle file: {e}") from e
    if len(data) % RECORD.size:
        raise ProviderError(f"Candle file length {len(data)} is not a multiple of {RECORD.size}")
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    bars: list[Bar] = []
    last = -1
    for secs, o, c, lo, hi, vol in RECORD.iter_unpack(data):
        if secs >= 86400 or secs <= last:
            raise ProviderError("Candle times are out of order or outside the day")
        last = secs
        if lo > min(o, c) or hi < max(o, c) or lo <= 0:
            # Guards against a changed record layout silently producing wrong prices.
            raise ProviderError("Candle record failed the low <= open/close <= high check")
        if vol == 0 and o == c == lo == hi:
            continue
        bars.append(
            Bar(
                ts=start + timedelta(seconds=secs),
                open=Decimal(o) / scale,
                high=Decimal(hi) / scale,
                low=Decimal(lo) / scale,
                close=Decimal(c) / scale,
                volume=Decimal(float(vol)).quantize(VOLUME_Q),
            )
        )
    return bars


# Requests from one process share a pace: Dukascopy answers bursts with HTTP 429.
_pace_lock = threading.Lock()
_last_request = 0.0


def _pace(min_interval: float) -> None:
    global _last_request
    with _pace_lock:
        wait = _last_request + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Seconds to wait before the next attempt. A 429 honours Retry-After (in seconds) and otherwise backs off
    from 2 s; other failures back off from 0.5 s. Both are capped."""
    if response is not None and response.status_code == 429:
        try:
            return min(60.0, max(1.0, float(response.headers.get("Retry-After", ""))))
        except ValueError:
            return min(30.0, 2.0 * 2**attempt)
    return min(10.0, 0.5 * 2**attempt)


class DukascopyProvider:
    info = INFO

    def __init__(self, base_url: str, timeout: float = 60.0, retries: int = 6, client: httpx.Client | None = None,
                 min_interval: float = 0.5):  # fmt: skip
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.min_interval = min_interval
        self._client = client

    def provider_symbol(self, symbol: str, asset_class: str) -> str | None:
        sym = symbol.upper().replace("/", "").replace(".", "")
        return sym if asset_class == "forex" and sym in PAIRS else None

    def fetch_day(self, provider_symbol: str, day: date, side: str) -> list[Bar]:
        if side not in ("bid", "ask"):
            raise ValueError(side)
        raw = self._get(day_path(provider_symbol, day, side))
        return decode_candles(raw, day, price_scale(provider_symbol))

    def _get(self, path: str) -> bytes:
        url = f"{self.base_url}/{path}"
        if url.startswith("file://"):
            p = Path(urlparse(url).path)
            return p.read_bytes() if p.exists() else b""
        client = self._client or httpx.Client(timeout=self.timeout, headers={"User-Agent": "EdgeLedger/0.4"})
        try:
            for attempt in range(self.retries + 1):
                r: httpx.Response | None = None
                _pace(self.min_interval)
                try:
                    r = client.get(url)
                except httpx.TransportError as e:
                    err: str = f"{type(e).__name__}: {e}"
                else:
                    if r.status_code == 404:
                        return b""
                    if r.status_code == 200:
                        return r.content
                    if r.status_code not in (429, 500, 502, 503, 504):
                        raise ProviderUnavailable(f"Dukascopy answered HTTP {r.status_code}")
                    err = f"HTTP {r.status_code}"
                if attempt < self.retries:
                    time.sleep(retry_delay(attempt, r))
            raise ProviderUnavailable(f"Dukascopy unreachable after {self.retries + 1} attempts ({err})")
        finally:
            if self._client is None:
                client.close()

"""Builds Dukascopy-format candle files for tests. These are generated test fixtures, not market history."""

import lzma
import struct
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.marketdata.providers.dukascopy import day_path, price_scale

REC = struct.Struct(">IIIIIf")


def encode(records: list[tuple[int, str, str, str, str, float]], symbol: str) -> bytes:
    """records: (seconds since 00:00 UTC, open, high, low, close, volume) with prices as decimal strings."""
    scale = price_scale(symbol)
    raw = b"".join(
        REC.pack(secs, *(int(Decimal(p) * scale) for p in (o, c, lo, hi)), vol) for secs, o, hi, lo, c, vol in records
    )
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def write_day(root: Path, symbol: str, day: date, side: str, bars: dict[str, tuple[str, str, str, str]],
              volume: float = 1.5) -> None:  # fmt: skip
    """bars: {"HH:MM": (open, high, low, close)}. Every other minute of the day is written as a flat zero-volume bar,
    the way Dukascopy encodes minutes without ticks."""
    records = []
    filler = next(iter(bars.values()))[3] if bars else "1"
    for m in range(1440):
        key = f"{m // 60:02d}:{m % 60:02d}"
        if key in bars:
            o, h, lo, c = bars[key]
            records.append((m * 60, o, h, lo, c, volume))
        else:
            records.append((m * 60, filler, filler, filler, filler, 0.0))
    p = root / day_path(symbol, day, side)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode(records, symbol))


# 2024-01-16 (Tuesday). Ask is the bid plus 0.00010.
DAY = date(2024, 1, 16)
BID = {
    "09:58": ("1.08990", "1.09000", "1.08980", "1.08995"),
    "09:59": ("1.08995", "1.09005", "1.08990", "1.09000"),
    "10:00": ("1.09000", "1.09010", "1.08800", "1.08990"),  # the low happens before the 10:00:30 entry
    "10:01": ("1.08990", "1.09010", "1.08980", "1.09000"),
    "10:02": ("1.09000", "1.09020", "1.08950", "1.09010"),
    "10:03": ("1.09010", "1.09080", "1.09000", "1.09060"),
    "10:04": ("1.09060", "1.09060", "1.09030", "1.09040"),
    "10:05": ("1.09040", "1.09200", "1.09040", "1.09050"),  # the high happens after the 10:05:20 exit
    "10:06": ("1.09050", "1.09060", "1.09040", "1.09045"),
    "10:20": ("1.09045", "1.09050", "1.09040", "1.09050"),
}


def ask_of(bars):
    return {k: tuple(str(Decimal(v) + Decimal("0.00010")) for v in ohlc) for k, ohlc in bars.items()}


def write_eurusd_fixture(root: Path) -> None:
    write_day(root, "EURUSD", DAY, "bid", BID)
    write_day(root, "EURUSD", DAY, "ask", ask_of(BID))

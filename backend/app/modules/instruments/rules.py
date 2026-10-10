"""Instrument-specific rules: contract multipliers, currencies, market timezones and session dates.

Session dates
-------------
Trades are bucketed into the market's trading date, not the UTC date:

* US equities, ETFs, options: America/New_York calendar date. Regular session 09:30-16:00 ET.
* CME-style futures: the session that opens at 17:00 America/Chicago belongs to the next calendar day
  (Sunday evening trading is Monday's session). Regular (RTH) session 08:30-15:15 CT.
* Forex: rolls at 17:00 America/New_York. "Regular" is the 08:00-17:00 ET New York/London overlap window.
* Crypto: UTC calendar date; every hour is "regular".

Exchange holidays and early closes are not modelled yet (see docs/metrics.md, Known limitations).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

# Point value per contract for common US futures roots (USD).
FUTURES_MULTIPLIERS: dict[str, Decimal] = {
    "ES": Decimal(50), "MES": Decimal(5), "NQ": Decimal(20), "MNQ": Decimal(2),
    "YM": Decimal(5), "MYM": Decimal("0.5"), "RTY": Decimal(50), "M2K": Decimal(5),
    "CL": Decimal(1000), "MCL": Decimal(100), "GC": Decimal(100), "MGC": Decimal(10),
    "SI": Decimal(5000), "NG": Decimal(10000), "ZB": Decimal(1000), "ZN": Decimal(1000),
    "6E": Decimal(125000),
}  # fmt: skip

FUTURES_TICKS: dict[str, Decimal] = {
    "ES": Decimal("0.25"), "MES": Decimal("0.25"), "NQ": Decimal("0.25"), "MNQ": Decimal("0.25"),
    "YM": Decimal(1), "MYM": Decimal(1), "CL": Decimal("0.01"), "MCL": Decimal("0.01"),
    "GC": Decimal("0.1"), "MGC": Decimal("0.1"),
}  # fmt: skip

MONTH_CODES = "FGHJKMNQUVXZ"
FUT_RE = re.compile(r"^/?(?P<root>[A-Z0-9]{1,4}?)(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{1,2})$")
# OCC option symbol, e.g. "AAPL  240315C00180000" or "AAPL240315C00180000"
OCC_RE = re.compile(r"^(?P<root>[A-Z.]{1,6})\s*(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")
FX_RE = re.compile(r"^(?P<base>[A-Z]{3})[/.]?(?P<quote>[A-Z]{3})$")
FX_CCY = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK"}


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    asset_class: str
    currency: str
    multiplier: Decimal
    tick_size: Decimal | None = None
    root_symbol: str | None = None
    underlying: str | None = None
    expiry: date | None = None
    strike: Decimal | None = None
    option_type: str | None = None


def normalize_symbol(symbol: str) -> str:
    return re.sub(r"\s+", " ", symbol.strip().upper())


def infer_spec(symbol: str, asset_class: str | None = None, currency: str | None = None,
               multiplier: Decimal | None = None) -> InstrumentSpec:  # fmt: skip
    """Infer an instrument specification. Explicit values from the import mapping always win."""
    sym = normalize_symbol(symbol)
    ac = (asset_class or "").strip().lower() or None
    aliases = {"equity": "stock", "stk": "stock", "fut": "future", "futures": "future", "opt": "option",
               "options": "option", "fx": "forex", "cash": "forex", "crypto": "crypto", "etf": "etf"}  # fmt: skip
    ac = aliases.get(ac, ac) if ac else None

    occ = OCC_RE.match(sym.replace(" ", "")) if ac in (None, "option") else None
    if occ:
        exp = date(2000 + int(occ["yy"]), int(occ["mm"]), int(occ["dd"]))
        return InstrumentSpec(
            symbol=sym.replace(" ", ""), asset_class="option", currency=currency or "USD",
            multiplier=multiplier or Decimal(100), underlying=occ["root"], expiry=exp,
            strike=Decimal(occ["strike"]) / 1000, option_type="call" if occ["cp"] == "C" else "put",
        )  # fmt: skip
    if ac == "option":
        return InstrumentSpec(sym, "option", currency or "USD", multiplier or Decimal(100))

    fut = FUT_RE.match(sym)
    if ac == "future" or (ac is None and fut and fut["root"] in FUTURES_MULTIPLIERS):
        root = fut["root"] if fut else sym.lstrip("/")
        mult = multiplier or FUTURES_MULTIPLIERS.get(root)
        if mult is None:
            raise ValueError(f"Unknown futures root {root!r}: provide a multiplier column")
        return InstrumentSpec(sym.lstrip("/"), "future", currency or "USD", mult, FUTURES_TICKS.get(root), root)

    fx = FX_RE.match(sym)
    if ac == "forex" or (ac is None and fx and fx["base"] in FX_CCY and fx["quote"] in FX_CCY):
        if not fx:
            raise ValueError(f"Cannot parse forex pair {sym!r}")
        # Quantity is in base-currency units; P&L accrues in the quote currency.
        return InstrumentSpec(f"{fx['base']}{fx['quote']}", "forex", currency or fx["quote"], multiplier or Decimal(1))

    if ac == "crypto":
        return InstrumentSpec(sym, "crypto", currency or "USD", multiplier or Decimal(1))
    return InstrumentSpec(sym, ac or "stock", currency or "USD", multiplier or Decimal(1))


@dataclass(frozen=True)
class MarketCalendar:
    tz: ZoneInfo
    rollover: time | None  # local time at which the next session date begins
    regular_start: time | None
    regular_end: time | None


CALENDARS = {
    "equity": MarketCalendar(ZoneInfo("America/New_York"), None, time(9, 30), time(16, 0)),
    "future": MarketCalendar(ZoneInfo("America/Chicago"), time(17, 0), time(8, 30), time(15, 15)),
    "forex": MarketCalendar(ZoneInfo("America/New_York"), time(17, 0), time(8, 0), time(17, 0)),
    "crypto": MarketCalendar(ZoneInfo("UTC"), None, None, None),
}


def calendar_for(asset_class: str) -> MarketCalendar:
    if asset_class in ("stock", "etf", "option"):
        return CALENDARS["equity"]
    return CALENDARS[asset_class]


def session_date(ts: datetime, asset_class: str) -> date:
    cal = calendar_for(asset_class)
    local = ts.astimezone(cal.tz)
    d = local.date()
    if cal.rollover is not None and local.time() >= cal.rollover:
        d += timedelta(days=1)
    # Weekend rollover: Saturday/Sunday sessions belong to Monday.
    if cal.rollover is not None:
        while d.weekday() >= 5:
            d += timedelta(days=1)
    return d


def entry_session(ts: datetime, asset_class: str) -> str:
    cal = calendar_for(asset_class)
    if cal.regular_start is None or cal.regular_end is None:
        return "regular"
    t = ts.astimezone(cal.tz).time()
    return "regular" if cal.regular_start <= t < cal.regular_end else "extended"


def market_local_time(ts: datetime, asset_class: str) -> datetime:
    return ts.astimezone(calendar_for(asset_class).tz)

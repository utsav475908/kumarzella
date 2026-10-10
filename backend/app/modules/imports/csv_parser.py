"""CSV decoding, column-mapping suggestion and row normalization. No database access here."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.core.money import D
from app.modules.imports.schemas import ColumnMapping, ImportOptions
from app.modules.instruments.rules import InstrumentSpec, infer_spec

SIDE_VALUES = {
    "buy": "buy", "b": "buy", "bot": "buy", "bought": "buy", "buy to open": "buy", "buy to cover": "buy",
    "bto": "buy", "btc": "buy", "cover": "buy", "long": "buy",
    "sell": "sell", "s": "sell", "sld": "sell", "sold": "sell", "sell short": "sell", "short": "sell",
    "sell to open": "sell", "sell to close": "sell", "sto": "sell", "stc": "sell", "ss": "sell",
}  # fmt: skip

DATETIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
    "%Y%m%d %H:%M:%S", "%Y%m%d %H%M%S", "%Y%m%d;%H%M%S", "%d.%m.%Y %H:%M:%S",
]  # fmt: skip

HEADER_SYNONYMS: dict[str, list[str]] = {
    "timestamp": ["datetime", "date/time", "timestamp", "time stamp", "execution time", "exec time", "filled time",
                  "trade time", "fill time", "date time"],
    "date": ["date", "trade date", "exec date"],
    "time": ["time", "exec time of day"],
    "symbol": ["symbol", "ticker", "instrument", "contract", "underlying symbol", "security"],
    "side": ["side", "action", "buy/sell", "b/s", "direction", "transaction type", "type"],
    "quantity": ["quantity", "qty", "shares", "contracts", "size", "filled qty", "amount", "units"],
    "price": ["price", "fill price", "exec price", "avg price", "execution price", "t. price", "trade price"],
    "commission": ["commission", "commissions", "comm", "comm/fee", "ib commission"],
    "fees": ["fees", "fee", "reg fees", "exchange fees", "other fees", "misc fees"],
    "execution_id": ["execution id", "exec id", "execid", "fill id", "trade id", "order id", "id", "transaction id"],
    "asset_class": ["asset class", "asset category", "asset type", "security type", "sec type", "instrument type"],
    "currency": ["currency", "ccy"],
    "multiplier": ["multiplier", "mult", "point value", "contract size"],
}  # fmt: skip

PRESETS: dict[str, dict] = {
    "generic": {
        "name": "Generic executions CSV",
        "description": "One row per fill with Date/Time, Symbol, Side, Quantity, Price, Commission, Fees, Exec ID.",
        "mapping": {"timestamp": "Date/Time", "symbol": "Symbol", "side": "Side", "quantity": "Quantity",
                    "price": "Price", "commission": "Commission", "fees": "Fees", "execution_id": "Exec ID"},
        "options": {"timezone": "America/New_York"},
    },
    "signed_quantity": {
        "name": "Signed quantity (no side column)",
        "description": "Positive quantity = buy, negative = sell. Common in broker activity statements.",
        "mapping": {"date": "TradeDate", "time": "TradeTime", "symbol": "Symbol", "quantity": "Quantity",
                    "price": "TradePrice", "commission": "Commission", "execution_id": "TradeID",
                    "asset_class": "AssetClass", "currency": "Currency", "multiplier": "Multiplier"},
        "options": {"timezone": "America/New_York", "side_from_quantity_sign": True},
    },
}  # fmt: skip


class CsvError(ValueError):
    pass


def decode(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise CsvError("File looks binary, not a CSV text file")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CsvError("Unable to decode file as text")


def read_csv(data: bytes, max_rows: int) -> tuple[list[str], list[dict[str, str]]]:
    text = decode(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        raise CsvError("File is empty")
    if not any(headers):
        raise CsvError("Header row is empty")
    if len(set(headers)) != len(headers):
        raise CsvError("Duplicate column names in header row")
    rows: list[dict[str, str]] = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        if len(rows) >= max_rows:
            raise CsvError(f"File exceeds the {max_rows} row limit")
        row = {h: (values[i].strip() if i < len(values) else "") for i, h in enumerate(headers)}
        if len(values) > len(headers):
            row["__extra__"] = "|".join(values[len(headers) :])
        rows.append(row)
    if not rows:
        raise CsvError("File has a header but no data rows")
    return headers, rows


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9/.]+", " ", h.lower()).strip()


def suggest_mapping(headers: list[str]) -> tuple[dict, str | None]:
    """Return a best-guess mapping and the preset whose columns match exactly, if any."""
    for key, p in PRESETS.items():
        if all(v in headers for v in p["mapping"].values()):
            return dict(p["mapping"]), key
    normalized = {_norm(h): h for h in headers}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field_name, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            h = normalized.get(syn)
            if h and h not in used:
                mapping[field_name] = h
                used.add(h)
                break
    if "timestamp" in mapping:
        mapping.pop("date", None)
        mapping.pop("time", None)
    return mapping, None


@dataclass
class NormalizedRow:
    executed_at: datetime
    spec: InstrumentSpec
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    fees: Decimal
    source_execution_id: str | None
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "executed_at": self.executed_at.isoformat(),
            "symbol": self.spec.symbol,
            "asset_class": self.spec.asset_class,
            "currency": self.spec.currency,
            "multiplier": str(self.spec.multiplier),
            "side": self.side,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "commission": str(self.commission),
            "fees": str(self.fees),
            "source_execution_id": self.source_execution_id,
        }

    def base_fingerprint(self, account_id: str) -> str:
        parts = [account_id, self.spec.symbol, self.spec.asset_class, self.side, _canon(self.quantity),
                 _canon(self.price), self.executed_at.astimezone(UTC).isoformat()]  # fmt: skip
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _canon(d: Decimal) -> str:
    return format(d.normalize(), "f")


def fingerprint(base: str, occurrence: int, source_execution_id: str | None) -> str:
    """Stable identity of an execution for duplicate detection.

    With a broker execution id the id itself is the identity. Without one, identical fills in a file are
    distinguished by their occurrence index, so re-importing the same file never creates duplicates while two
    genuinely identical fills in one file are both kept.
    """
    key = f"id:{source_execution_id}" if source_execution_id else f"fp:{base}:{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()


def _get(row: dict[str, str], col: str | None) -> str:
    return row.get(col, "").strip() if col else ""


def parse_decimal(value: str, field_name: str) -> Decimal:
    v = value.strip().replace("$", "").replace(" ", "")
    neg = v.startswith("(") and v.endswith(")")
    v = v.strip("()")
    try:
        d = D(v)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name}: '{value}' is not a number")
    if not d.is_finite():
        raise ValueError(f"{field_name}: '{value}' is not a finite number")
    return -d if neg else d


def parse_timestamp(value: str, opts: ImportOptions) -> tuple[datetime, bool]:
    """Returns (utc timestamp, was_naive)."""
    v = value.strip().replace("Z", "+00:00")
    formats = [opts.datetime_format] if opts.datetime_format else DATETIME_FORMATS
    for fmt in formats:
        try:
            dt = datetime.strptime(v, fmt)
            break
        except ValueError:
            continue
    else:
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"timestamp: '{value}' does not match a supported date/time format")
    naive = dt.tzinfo is None
    if naive:
        dt = dt.replace(tzinfo=ZoneInfo(opts.timezone))
    return dt.astimezone(UTC), naive


def normalize_row(row: dict[str, str], m: ColumnMapping, opts: ImportOptions, now: datetime) -> NormalizedRow:
    """Validate and normalize one row. Raises ValueError with all problems joined by '; '."""
    errors: list[str] = []
    warnings: list[str] = []

    executed_at: datetime | None = None
    ts_raw = _get(row, m.timestamp) if m.timestamp else " ".join(x for x in (_get(row, m.date), _get(row, m.time)) if x)
    if not ts_raw:
        errors.append("timestamp: missing")
    else:
        try:
            executed_at, naive = parse_timestamp(ts_raw, opts)
            if naive:
                warnings.append(f"timestamp had no offset; interpreted in {opts.timezone}")
            if m.date and not m.time and not m.timestamp:
                warnings.append("no time column; fills on the same day are ordered by row number")
            if executed_at > now:
                errors.append("timestamp: in the future")
        except ValueError as e:
            errors.append(str(e))

    symbol = _get(row, m.symbol)
    if not symbol:
        errors.append("symbol: missing")

    qty: Decimal | None = None
    try:
        raw_qty = _get(row, m.quantity)
        if not raw_qty:
            raise ValueError("quantity: missing")
        qty = parse_decimal(raw_qty, "quantity")
    except ValueError as e:
        errors.append(str(e))

    side: str | None = None
    raw_side = _get(row, m.side)
    if raw_side:
        key = raw_side.strip().lower()
        side = opts.side_aliases.get(raw_side) or opts.side_aliases.get(key) or SIDE_VALUES.get(key)
        if side is None:
            errors.append(f"side: unrecognized value '{raw_side}'")
    elif opts.side_from_quantity_sign and qty is not None:
        side = "buy" if qty > 0 else "sell"
    else:
        errors.append("side: missing (map a side column or enable 'side from quantity sign')")
    if qty is not None:
        if qty == 0:
            errors.append("quantity: must not be zero")
        elif qty < 0 and raw_side:
            warnings.append("negative quantity with explicit side; absolute value used")
        qty = abs(qty)

    price: Decimal | None = None
    try:
        raw_price = _get(row, m.price)
        if not raw_price:
            raise ValueError("price: missing")
        price = parse_decimal(raw_price, "price")
        if price < 0:
            errors.append("price: must not be negative")
        elif price == 0:
            warnings.append("price is zero (expiry/assignment?)")
    except ValueError as e:
        errors.append(str(e))

    costs: dict[str, Decimal] = {}
    for name, col in (("commission", m.commission), ("fees", m.fees)):
        raw = _get(row, col)
        if not raw:
            costs[name] = Decimal(0)
            continue
        try:
            c = parse_decimal(raw, name)
            if c < 0:
                # Brokers commonly report costs as negative cash flows.
                c = -c
            costs[name] = c
        except ValueError as e:
            errors.append(str(e))

    multiplier = None
    if m.multiplier and _get(row, m.multiplier):
        try:
            multiplier = parse_decimal(_get(row, m.multiplier), "multiplier")
            if multiplier <= 0:
                errors.append("multiplier: must be positive")
                multiplier = None
        except ValueError as e:
            errors.append(str(e))

    spec: InstrumentSpec | None = None
    if symbol:
        try:
            ac = _get(row, m.asset_class) or opts.default_asset_class
            ccy = (_get(row, m.currency) or None) if m.currency else None
            if ccy and not re.fullmatch(r"[A-Za-z]{3}", ccy):
                errors.append(f"currency: '{ccy}' is not an ISO code")
                ccy = None
            spec = infer_spec(symbol, ac, ccy.upper() if ccy else None, multiplier)
        except ValueError as e:
            errors.append(f"instrument: {e}")

    if errors:
        raise ValueError("; ".join(errors))
    assert executed_at and spec and side and qty is not None and price is not None
    exec_id = _get(row, m.execution_id) or None
    return NormalizedRow(executed_at, spec, side, qty, price, costs["commission"], costs["fees"], exec_id, warnings)

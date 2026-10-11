"""Live check of the Dukascopy adapter against the real datafeed (needs network access to datafeed.dukascopy.com).

    python -m scripts.check_dukascopy                  # EURUSD and USDJPY on 2024-01-16
    python -m scripts.check_dukascopy GBPUSD 2024-03-05

Exits non-zero if a file cannot be fetched or decoded, or if the prices fail basic sanity checks.
"""

import sys
from datetime import date
from decimal import Decimal

from app.core.config import get_settings
from app.modules.marketdata.providers.dukascopy import DukascopyProvider

# Loose 2020s ranges, only to catch a wrong price scale or field order.
PLAUSIBLE = {"EURUSD": (Decimal("0.9"), Decimal("1.3")), "USDJPY": (Decimal("100"), Decimal("170")),
             "GBPUSD": (Decimal("1.0"), Decimal("1.5"))}  # fmt: skip


def check(p: DukascopyProvider, symbol: str, day: date) -> bool:
    bid = p.fetch_day(symbol, day, "bid")
    ask = p.fetch_day(symbol, day, "ask")
    print(f"{symbol} {day}: {len(bid)} bid bars, {len(ask)} ask bars")
    if not bid or not ask:
        print("  no bars (market closed that day?)")
        return False
    for label, b in (("first", bid[0]), ("last", bid[-1])):
        print(f"  {label} bid {b.ts:%H:%M} O {b.open} H {b.high} L {b.low} C {b.close} V {b.volume}")
    ok = True
    lo, hi = PLAUSIBLE.get(symbol, (Decimal(0), Decimal(10**6)))
    if not all(lo <= b.low and b.high <= hi for b in bid):
        print(f"  FAIL: bid prices outside {lo}-{hi}; price scale may be wrong")
        ok = False
    asks = {a.ts: a for a in ask}
    pairs = [(b, asks[b.ts]) for b in bid if b.ts in asks]
    wider = sum(1 for b, a in pairs if a.close >= b.close)
    print(f"  ask >= bid on {wider}/{len(pairs)} shared minutes")
    if pairs and wider / len(pairs) < 0.99:
        print("  FAIL: ask below bid too often; sides may be swapped")
        ok = False
    return ok


def main() -> int:
    s = get_settings()
    p = DukascopyProvider(s.dukascopy_base_url, s.marketdata_timeout_seconds, s.marketdata_retries)
    args = sys.argv[1:]
    targets = [(args[0], date.fromisoformat(args[1]))] if len(args) == 2 else [
        ("EURUSD", date(2024, 1, 16)), ("USDJPY", date(2024, 1, 16))]  # fmt: skip
    results = [check(p, sym, d) for sym, d in targets]
    print("OK" if all(results) else "FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

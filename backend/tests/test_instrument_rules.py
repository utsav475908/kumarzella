from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from app.modules.instruments.rules import entry_session, infer_spec, session_date


def test_infer_stock_default():
    s = infer_spec("aapl")
    assert (s.symbol, s.asset_class, s.multiplier, s.currency) == ("AAPL", "stock", D(1), "USD")


def test_infer_futures_contract_month():
    s = infer_spec("ESH4")
    assert s.asset_class == "future" and s.root_symbol == "ES" and s.multiplier == D(50)
    assert infer_spec("/MNQZ24").multiplier == D(2)


def test_unknown_futures_root_requires_multiplier():
    with pytest.raises(ValueError):
        infer_spec("ZZZH4", asset_class="future")
    assert infer_spec("ZZZH4", asset_class="future", multiplier=D(10)).multiplier == D(10)


def test_infer_occ_option():
    s = infer_spec("AAPL  240315C00180000")
    assert s.asset_class == "option" and s.multiplier == D(100)
    assert s.strike == D("180") and s.option_type == "call" and s.expiry == date(2024, 3, 15)


def test_infer_forex_quote_currency():
    s = infer_spec("EUR/JPY")
    assert s.symbol == "EURJPY" and s.asset_class == "forex" and s.currency == "JPY"


def test_equity_session_date_uses_new_york_not_utc():
    # 2024-03-05 01:00 UTC is 2024-03-04 20:00 in New York
    ts = datetime(2024, 3, 5, 1, 0, tzinfo=UTC)
    assert session_date(ts, "stock") == date(2024, 3, 4)
    assert entry_session(ts, "stock") == "extended"
    assert entry_session(datetime(2024, 3, 4, 15, 0, tzinfo=UTC), "stock") == "regular"  # 10:00 ET


def test_futures_evening_session_belongs_to_next_day():
    # Tue 2024-03-05 23:30 UTC = 17:30 CT -> Wednesday session
    assert session_date(datetime(2024, 3, 5, 23, 30, tzinfo=UTC), "future") == date(2024, 3, 6)
    # Sun 2024-03-10 23:00 UTC = 18:00 CDT (after DST switch) -> Monday session
    assert session_date(datetime(2024, 3, 10, 23, 0, tzinfo=UTC), "future") == date(2024, 3, 11)


def test_dst_transition_regular_session_boundary():
    # Before DST (EST, UTC-5): 14:30 UTC = 09:30 ET ; after DST (EDT, UTC-4): 13:30 UTC = 09:30 ET
    assert entry_session(datetime(2024, 3, 8, 14, 30, tzinfo=UTC), "stock") == "regular"
    assert entry_session(datetime(2024, 3, 11, 13, 30, tzinfo=UTC), "stock") == "regular"
    assert entry_session(datetime(2024, 3, 11, 13, 29, tzinfo=UTC), "stock") == "extended"

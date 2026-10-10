"""Position engine regression tests. Expected values are computed by hand in the comments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.modules.positions.engine import Fill, reconstruct

T0 = datetime(2024, 3, 4, 14, 30, tzinfo=UTC)


def f(i, side, qty, price, costs="0", minutes=0, seq=0, source="import"):
    return Fill(str(i), side, D(qty), D(price), D(costs), T0 + timedelta(minutes=minutes), seq, source)


def test_simple_long_round_trip():
    r = reconstruct([f(1, "buy", 100, "10", "1"), f(2, "sell", 100, "11", "1", 5)], D(1))
    (t,) = r.trades
    assert t.direction == "long" and t.status == "closed"
    assert t.gross_pnl == D("100") and t.fees == D("2") and t.net_pnl == D("98")
    assert t.holding_seconds == 300
    assert r.position == 0


@pytest.mark.parametrize(
    "policy, partial_realized, final_realized",
    [("average_cost", D("100"), D("75")), ("fifo", D("150"), D("25"))],
)
def test_scale_in_scale_out_policies(policy, partial_realized, final_realized):
    # entry value 100*10 + 100*12 = 2200 ; exit value 50*13 + 150*11.5 = 2375 ; gross = 175 for both policies
    # avg cost: first exit removes 2200*50/200 = 550 basis -> 650-550 = 100
    # fifo: first exit removes 50 @10 = 500 basis -> 650-500 = 150
    fills = [
        f(1, "buy", 100, "10"),
        f(2, "buy", 100, "12", minutes=1),
        f(3, "sell", 50, "13", minutes=2),
        f(4, "sell", 150, "11.5", minutes=3),
    ]
    (t,) = reconstruct(fills, D(1), policy).trades
    assert t.gross_pnl == D("175")
    assert [a.role for a in t.allocations] == ["open", "add", "reduce", "close"]
    assert t.allocations[2].realized_pnl == partial_realized
    assert t.allocations[3].realized_pnl == final_realized
    assert t.entry_avg_price == D("11") and t.exit_avg_price == D("11.875")
    assert t.peak_qty == D("200")


def test_short_trade():
    (t,) = reconstruct([f(1, "sell", 10, "50"), f(2, "buy", 10, "45", minutes=1)], D(1)).trades
    assert t.direction == "short" and t.gross_pnl == D("50")


def test_reversal_splits_fill_and_costs():
    # buy 100@10 (cost 1); sell 150@12 (cost 3 -> 2 closing, 1 opening); buy 50@11 (cost 0.5)
    fills = [f(1, "buy", 100, "10", "1"), f(2, "sell", 150, "12", "3", 1), f(3, "buy", 50, "11", "0.5", 2)]
    r = reconstruct(fills, D(1))
    long_t, short_t = r.trades
    assert long_t.direction == "long" and long_t.gross_pnl == D("200") and long_t.fees == D("3")
    assert short_t.direction == "short" and short_t.anchor_execution_id == "2" and short_t.anchor_leg == 1
    assert short_t.entry_qty == D("50") and short_t.entry_avg_price == D("12")
    assert short_t.gross_pnl == D("50") and short_t.fees == D("1.5")
    assert short_t.status == "closed" and r.position == 0


def test_futures_multiplier():
    # ES: 2.5 points * 2 contracts * $50
    fills = [f(1, "buy", 2, "4500.25", "4.20"), f(2, "sell", 2, "4502.75", "4.20", 10)]
    (t,) = reconstruct(fills, D(50)).trades
    assert t.gross_pnl == D("250") and t.net_pnl == D("241.60")


def test_option_expiring_worthless():
    (t,) = reconstruct([f(1, "buy", 1, "2.50", "0.65"), f(2, "sell", 1, "0", "0", 60)], D(100)).trades
    assert t.gross_pnl == D("-250") and t.net_pnl == D("-250.65")


def test_open_trade_reports_realized_partial_only():
    r = reconstruct([f(1, "buy", 100, "10"), f(2, "sell", 40, "11", minutes=1)], D(1))
    (t,) = r.trades
    assert t.status == "open" and t.open_qty == D("60") and t.gross_pnl == D("40")
    assert r.position == D("60") and r.avg_cost == D("10")


def test_same_timestamp_ordered_by_sequence():
    fills = [f(2, "sell", 10, "11", seq=2), f(1, "buy", 10, "10", seq=1)]
    (t,) = reconstruct(fills, D(1)).trades
    assert t.direction == "long" and t.gross_pnl == D("10")


def test_cost_split_sums_exactly():
    fills = [f(1, "buy", 1, "10"), f(2, "sell", 3, "10", "1.00", 1)]
    long_t, short_t = reconstruct(fills, D(1)).trades
    assert long_t.fees + short_t.fees == D("1.00")
    assert long_t.fees == D("0.33333333")


def test_many_partial_fills_multiple_trades_deterministic():
    fills = [
        f(1, "buy", 30, "20"),
        f(2, "buy", 20, "20.5", minutes=1),
        f(3, "sell", 50, "21", minutes=2),
        f(4, "sell", 10, "21", minutes=3),
        f(5, "buy", 10, "20", minutes=4),
    ]
    a = reconstruct(fills, D(1))
    b = reconstruct(list(reversed(fills)), D(1))
    assert [(t.anchor_execution_id, t.gross_pnl) for t in a.trades] == [
        (t.anchor_execution_id, t.gross_pnl) for t in b.trades
    ]
    # trade 1: entry 600+410=1010, exit 1050 -> 40 ; trade 2: short 10 @21 cover @20 -> 10
    assert [t.gross_pnl for t in a.trades] == [D("40"), D("10")]


def test_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        reconstruct([f(1, "buy", 0, "10")], D(1))

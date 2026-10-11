"""Deterministic order simulator: fill rules, slippage, brackets, ambiguity and reproducibility (pure)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.modules.backtesting import simulator as sim
from app.modules.marketdata.providers.base import Bar

T0 = datetime(2024, 1, 17, 9, 0, tzinfo=UTC)
SPREAD = D("0.0001")
CFG = sim.Config(commission_per_100k=D("3.50"), slippage=D("0"))


def minute(i: int, o: str, h: str, low: str, c: str) -> tuple[Bar, Bar]:
    ts = T0 + timedelta(minutes=i)
    bid = Bar(ts, D(o), D(h), D(low), D(c), D(1))
    ask = Bar(ts, D(o) + SPREAD, D(h) + SPREAD, D(low) + SPREAD, D(c) + SPREAD, D(1))
    return bid, ask


def order(key: str, seq: int, side: str, typ: str, qty="100000", price=None, at=0, sl=None, tp=None) -> sim.Order:
    return sim.Order(key, seq, "entry", side, typ, D(qty), D(price) if price else None, T0 + timedelta(minutes=at),
                     D(sl) if sl else None, D(tp) if tp else None)  # fmt: skip


def run(orders: list[sim.Order], minutes, cfg=CFG) -> tuple[sim.State, sim.Events]:
    s = sim.State(pending=list(orders), next_seq=100)
    out = sim.Events()
    for b, a in minutes:
        ev = sim.step(s, cfg, b, a)
        out.fills += ev.fills
        out.cancels += ev.cancels
        out.created += ev.created
    return s, out


def test_market_orders_fill_at_the_next_open_on_the_right_side_with_slippage():
    cfg = sim.Config(commission_per_100k=D("3.50"), slippage=D("0.00002"))
    m = [minute(0, "1.09000", "1.09050", "1.08950", "1.09020")]
    s, ev = run([order("a", 1, "buy", "market", qty="250000")], m, cfg)
    (f,) = ev.fills
    assert f.price == D("1.09012")  # ask open 1.09010 + 0.00002 slippage
    assert f.commission == D("8.75") and s.position == D("250000")
    s, ev = run([order("b", 1, "sell", "market")], m, cfg)
    assert ev.fills[0].price == D("1.08998")  # bid open - slippage


def test_order_waits_for_its_first_minute():
    m = [minute(0, "1.09", "1.091", "1.089", "1.09"), minute(1, "1.0905", "1.091", "1.090", "1.0907")]
    _, ev = run([order("a", 1, "buy", "market", at=1)], m)
    assert [f.ts for f in ev.fills] == [T0 + timedelta(minutes=1)] and ev.fills[0].price == D("1.0906")


def test_limit_and_stop_rules_including_gaps():
    m = [minute(0, "1.09000", "1.09100", "1.08900", "1.09000")]
    # buy limit fills when the ask low reaches it, at the limit (no slippage on limits)
    _, ev = run([order("l", 1, "buy", "limit", price="1.08950")], m)
    assert ev.fills[0].price == D("1.08950")
    # a buy limit above the ask open fills at the better open price
    _, ev = run([order("l", 1, "buy", "limit", price="1.09500")], m)
    assert ev.fills[0].price == D("1.09010")
    # sell stop below the market triggers on the bid low; untouched levels never fill
    _, ev = run([order("s", 1, "sell", "stop", price="1.08920"), order("x", 2, "sell", "stop", price="1.08800")], m)
    assert [(f.order_key, f.price) for f in ev.fills] == [("s", D("1.08920"))]
    # gap: the bar opens below a sell stop, so it fills at the open
    gap = [minute(0, "1.08500", "1.08600", "1.08400", "1.08550")]
    _, ev = run([order("s", 1, "sell", "stop", price="1.08920")], gap)
    assert ev.fills[0].price == D("1.08500") and not ev.fills[0].ambiguous


def test_bracket_take_profit_and_one_cancels_the_other():
    m = [
        minute(0, "1.09000", "1.09010", "1.08990", "1.09000"),
        minute(1, "1.09000", "1.09080", "1.08990", "1.09070"),
    ]
    s, ev = run([order("e", 1, "buy", "market", sl="1.08900", tp="1.09050")], m)
    assert [c.kind for c in ev.created] == ["stop_loss", "take_profit"]
    assert [(f.order_key, f.price) for f in ev.fills] == [("e", D("1.09010")), ("e:take_profit", D("1.09050"))]
    assert [c.order_key for c in ev.cancels] == ["e:stop_loss"] and s.position == 0 and s.pending == []


def test_stop_and_target_in_the_same_minute_is_ambiguous_and_conservative():
    m = [minute(0, "1.09000", "1.09010", "1.08990", "1.09000"), minute(1, "1.09000", "1.09100", "1.08850", "1.09000")]
    _, ev = run([order("e", 1, "buy", "market", sl="1.08900", tp="1.09050")], m)
    entry, exit_ = ev.fills
    assert exit_.order_key == "e:stop_loss" and exit_.price == D("1.08900") and exit_.ambiguous
    assert "unknown" in exit_.reason


def test_mid_bar_entry_lets_only_the_stop_fill_in_that_minute():
    # Limit entry fills mid-minute; the same minute also reaches the target and the stop.
    m = [minute(0, "1.09000", "1.09100", "1.08800", "1.09000")]
    _, ev = run([order("e", 1, "buy", "limit", price="1.08950", sl="1.08850", tp="1.09050")], m)
    assert [f.order_key for f in ev.fills] == ["e", "e:stop_loss"] and ev.fills[1].ambiguous
    # Only the target is touched: it waits for the next minute
    m2 = [minute(0, "1.09000", "1.09100", "1.08940", "1.09000"), minute(1, "1.09000", "1.09060", "1.08990", "1.09000")]
    _, ev = run([order("e", 1, "buy", "limit", price="1.08950", sl="1.08850", tp="1.09050")], m2)
    assert [(f.order_key, f.ts.minute) for f in ev.fills] == [("e", 0), ("e:take_profit", 1)]


def test_protective_orders_cancel_when_position_is_closed_by_hand():
    m = [minute(0, "1.09", "1.0901", "1.0899", "1.09"), minute(1, "1.09", "1.0901", "1.0899", "1.09")]
    s, ev = run([order("e", 1, "buy", "market", sl="1.0800"), order("x", 2, "sell", "market", at=1)], m)
    assert s.position == 0 and [c.order_key for c in ev.cancels] == ["e:stop_loss"]


def test_reversal_and_reduce_only_quantity():
    m = [minute(0, "1.09", "1.0901", "1.0899", "1.09"), minute(1, "1.09", "1.0901", "1.0899", "1.09")]
    s, ev = run(
        [order("e", 1, "buy", "market", qty="100000", sl="1.08"), order("r", 2, "sell", "market", qty="300000", at=1)],
        m,
    )
    assert s.position == D("-200000")
    assert [c.order_key for c in ev.cancels] == ["e:stop_loss"]  # it would now add to the short


def test_flatten_and_rerun_reproduce_the_same_fills():
    minutes = [minute(i, "1.0900", "1.0906", "1.0894", "1.0903") for i in range(10)]
    log = [
        sim.LoggedOrder(order("a", 1, "buy", "limit", price="1.0895", at=0, sl="1.0880", tp="1.0905"), T0),
        sim.LoggedOrder(
            order("b", 2, "sell", "stop", price="1.0880", at=3), T0 + timedelta(minutes=3), T0 + timedelta(minutes=5)
        ),  # fmt: skip
        sim.LoggedOrder(order("c", 3, "sell", "market", at=6), T0 + timedelta(minutes=6)),
    ]
    first = sim.rerun(CFG, log, {}, minutes, finish=(T0 + timedelta(minutes=10), "finish"))
    second = sim.rerun(CFG, list(reversed(log)), {}, minutes, finish=(T0 + timedelta(minutes=10), "finish"))
    assert first == second and len(first) >= 3
    assert first[-1].order_key == "finish" and "finished" in first[-1].reason

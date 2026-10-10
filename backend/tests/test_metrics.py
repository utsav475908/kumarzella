"""Financial regression tests for aggregate metrics. Expected values come from fixture_a_expected.json,
which was computed by hand (see tests/fixtures/README.md), not by this code."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from app.modules.analytics import metrics as mx
from tests.helpers import all_trades, create_account, expected, import_file

EXP = expected("fixture_a_expected.json")["metrics"]


def row(net, day=1, gross=None, fees="0", r=None, risk=None, direction="long", hold=60, acct=None, **kw):
    t0 = datetime(2024, 1, day, 15, 0, tzinfo=UTC)
    return mx.TradeRow(
        id=uuid.uuid4(), account_id=acct or uuid.UUID(int=1), symbol=kw.get("symbol", "X"), asset_class="stock",
        direction=direction, opened_at=t0, closed_at=t0 + timedelta(seconds=hold), session_date=date(2024, 1, day),
        entry_session="regular", entry_hour=10, gross_pnl=D(gross if gross is not None else net), fees=D(fees),
        net_pnl=D(net), holding_seconds=hold, initial_risk=D(risk) if risk else None,
        r_multiple=D(r) if r else None, followed_plan=kw.get("followed_plan"),
        mistake_tags=tuple(kw.get("mistakes", ())),
    )  # fmt: skip


def test_dashboard_matches_hand_computed_fixture(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    d = auth_client.get("/api/v1/analytics/dashboard").json()
    s = d["summary"]
    for k in ("closed_trades", "wins", "losses", "breakevens", "max_consecutive_wins", "max_consecutive_losses",
              "avg_holding_seconds", "trading_days", "profitable_days"):  # fmt: skip
        assert s[k] == EXP[k], k
    for k in ("gross_pnl", "fees", "net_pnl", "win_rate", "profit_factor", "expectancy", "avg_win", "avg_loss",
              "median_trade", "max_drawdown"):  # fmt: skip
        assert D(s[k]) == D(EXP[k]), k
    assert d["open_trades"] == EXP["open_trades"]
    assert {x["date"]: D(x["net_pnl"]) for x in d["daily"]} == {k: D(v) for k, v in EXP["daily"].items()}
    assert {x["key"]: D(x["net_pnl"]) for x in d["by_direction"]} == {
        "long": D(EXP["long_net"]),
        "short": D(EXP["short_net"]),
    }
    assert {x["label"]: D(x["net_pnl"]) for x in d["by_weekday"]} == {k: D(v) for k, v in EXP["weekday"].items()}
    assert D(d["equity_curve"][-1]["cumulative"]) == D(EXP["net_pnl"])
    assert d["mae_mfe"]["available"] is False
    assert any("Small sample" in w for w in d["warnings"])


def test_filters_apply_consistently_to_kpis_and_table(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    for params in ({"direction": "short"}, {"asset_class": "future"}, {"date_from": "2024-03-05", "date_to": "2024-03-06"},
                   {"symbol": "AAPL"}, {"session": "regular"}):  # fmt: skip
        dash = auth_client.get("/api/v1/analytics/dashboard", params=params).json()
        rows = [t for t in all_trades(auth_client, **params) if t["status"] == "closed"]
        assert dash["summary"]["closed_trades"] == len(rows), params
        assert D(dash["summary"]["net_pnl"] or 0) == sum((D(t["net_pnl"]) for t in rows), D(0)), params


def test_empty_dataset_returns_nulls_not_zeros(auth_client):
    d = auth_client.get("/api/v1/analytics/dashboard").json()
    s = d["summary"]
    assert s["closed_trades"] == 0 and s["win_rate"] is None and s["profit_factor"] is None
    assert s["expectancy"] is None and d["equity_curve"] == [] and d["daily"] == []


def test_no_losses_profit_factor_is_null_with_reason():
    s = mx.summary([row("10"), row("5")])
    assert s["profit_factor"] is None and s["profit_factor_note"] == "no losing trades"
    assert s["win_rate"] == D("1")


def test_all_breakevens():
    s = mx.summary([row("0"), row("0")])
    assert s["win_rate"] is None and s["breakevens"] == 2 and s["expectancy"] == D("0.00")


def test_drawdown_from_initial_loss_counts_from_zero():
    _, dd = mx.equity_curve([row("-50", 1), row("20", 2), row("-40", 3)])
    # cumulative: -50, -30, -70 ; peak stays 0 -> max drawdown 70
    assert dd["max_drawdown"] == D("70")


def test_streaks_breakeven_resets():
    s = mx.streaks([row("1", 1), row("1", 2), row("0", 3), row("1", 4), row("-1", 5), row("-1", 6)])
    assert s["max_consecutive_wins"] == 2 and s["max_consecutive_losses"] == 2 and s["current_streak"] == -2


def test_r_metrics_ignore_missing_risk():
    s = mx.summary([row("100", r="2", risk="50"), row("-50", r="-1", risk="50"), row("30")])
    assert s["trades_with_r"] == 2 and s["avg_r"] == D("0.5") and s["total_r"] == D("1")


def test_costs_analysis():
    c = mx.costs([row("-1", gross="2", fees="3"), row("8", gross="10", fees="2")])
    assert c["total_fees"] == D("5.00") and c["trades_turned_negative_by_costs"] == 1
    assert c["fees_pct_of_gross_profit"] == D("0.4167")


def test_risk_adherence_flags():
    a = uuid.UUID(int=7)
    trades = [
        row("-150", 1, r="-1.5", risk="100", acct=a, followed_plan=False, mistakes=["Moved stop"]),
        row("-90", 1, r="-0.9", risk="300", acct=a, followed_plan=True),
        row("50", 2, acct=a),
    ]
    r = mx.risk_adherence(trades, {a: D("200")}, {a: D("200")})
    assert len(r["risk_limit_violations"]) == 1
    assert len(r["losses_beyond_planned_risk"]) == 1
    assert len(r["daily_loss_limit_breaches"]) == 1 and r["daily_loss_limit_breaches"][0]["net_pnl"] == D("-240.00")
    assert r["plan_adherence"]["not_followed"]["trades"] == 1 and r["plan_adherence"]["unrated"]["trades"] == 1
    assert r["mistakes"] == [{"tag": "Moved stop", "trades": 1, "net_pnl": D("-150.00")}]


def test_distribution_buckets_cover_all_trades():
    d = mx.distribution([row(str(x)) for x in (-100, -10, 0, 5, 50, 200)])
    assert sum(b["count"] for b in d["buckets"]) == 6


def test_multiple_currencies_never_mixed(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")  # USD
    auth_client.post("/api/v1/trades/manual", json={
        "account_id": acct["id"], "symbol": "EURJPY",
        "executions": [
            {"side": "buy", "quantity": "10000", "price": "160.10", "executed_at": "2024-04-02T09:00:00Z"},
            {"side": "sell", "quantity": "10000", "price": "160.30", "executed_at": "2024-04-02T10:00:00Z"},
        ]})  # fmt: skip
    usd = auth_client.get("/api/v1/analytics/dashboard", params={"currency": "USD"}).json()
    assert usd["excluded_other_currency_trades"] == 1 and D(usd["summary"]["net_pnl"]) == D("19.6")
    jpy = auth_client.get("/api/v1/analytics/dashboard", params={"currency": "JPY"}).json()
    assert D(jpy["summary"]["net_pnl"]) == D("2000")  # 0.20 x 10,000 units, in JPY
    assert set(usd["currencies_available"]) == {"USD", "JPY"}


def test_calendar_month(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    c = auth_client.get("/api/v1/analytics/calendar", params={"month": "2024-03-15"}).json()
    assert c["month"] == "2024-03" and len(c["days"]) == 4 and D(c["summary"]["net_pnl"]) == D("260.45")
    assert auth_client.get("/api/v1/analytics/calendar", params={"month": "2024-02-01"}).json()["days"] == []


def test_deposits_do_not_change_pnl(auth_client):
    acct = create_account(auth_client, starting_balance="10000")
    import_file(auth_client, acct["id"], "fixture_a.csv")
    before = auth_client.get("/api/v1/analytics/dashboard").json()["summary"]
    auth_client.post(f"/api/v1/accounts/{acct['id']}/cash-transactions",
                     json={"kind": "deposit", "amount": "50000", "occurred_at": "2024-03-05T00:00:00Z"})  # fmt: skip
    after = auth_client.get("/api/v1/analytics/dashboard").json()["summary"]
    assert before == after
    assert D(after["max_drawdown_pct_of_starting_balance"]) == D("0.0202")


def test_other_user_sees_no_analytics(auth_client, other_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    d = other_client.get("/api/v1/analytics/dashboard", params={"account_id": acct["id"]}).json()
    assert d["summary"]["closed_trades"] == 0


def test_money_is_serialized_as_strings_not_floats(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    d = auth_client.get("/api/v1/analytics/dashboard").json()
    assert d["summary"]["net_pnl"] == "260.45" and isinstance(d["daily"][0]["net_pnl"], str)
    t = all_trades(auth_client)[0]
    assert isinstance(t["net_pnl"], str)
    e = auth_client.get("/api/v1/exports/me").json()
    assert isinstance(e["executions"][0]["price"], str)

"""Manual backtesting through the API: blind bars, simulated orders, results, determinism and ownership."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from app.core.config import get_settings
from tests.md_helpers import ask_of, write_day

DAY2 = date(2024, 1, 17)


def ts(h, m):
    return int(datetime(2024, 1, 17, h, m, tzinfo=UTC).timestamp())


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    """08:00-08:59 flat around 1.09000, then 09:00-09:59 rising 0.5 pip a minute (generated test candles)."""
    bars = {}
    for i in range(60):
        bars[f"08:{i:02d}"] = ("1.09000", "1.09005", "1.08995", "1.09000")
    for i in range(60):
        o = D("1.09000") + D("0.00005") * i
        c = o + D("0.00005")
        bars[f"09:{i:02d}"] = (str(o), str(c + D("0.00002")), str(o - D("0.00002")), str(c))
    write_day(tmp_path, "EURUSD", DAY2, "bid", bars)
    write_day(tmp_path, "EURUSD", DAY2, "ask", ask_of(bars))
    s = get_settings()
    monkeypatch.setattr(s, "dukascopy_base_url", f"file://{tmp_path}")
    monkeypatch.setattr(s, "marketdata_provider", "dukascopy")
    return tmp_path


def create(client, **kw) -> dict:
    body = {"symbol": "EURUSD", "timeframe": "1m", "start_at": "2024-01-17T08:00:00Z", "end_at": "2024-01-17T10:00:00Z",
            "starting_balance": "10000", "commission_per_100k": "3.50", "slippage_pips": "0.2"} | kw  # fmt: skip
    r = client.post("/api/v1/backtests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def order(client, sid, **kw):
    return client.post(f"/api/v1/backtests/{sid}/orders", json={"side": "buy", "type": "market"} | kw)


def play_winning_long(client) -> dict:
    s = create(client)
    sid = s["id"]
    r = order(client, sid, quantity="100000", stop_loss="1.08900", take_profit="1.09100", note="range break")
    assert r.status_code == 201, r.text
    adv = client.post(f"/api/v1/backtests/{sid}/advance", json={"steps": 1}).json()
    assert adv["events"]["fills"] == 1
    p = client.patch(f"/api/v1/backtests/{sid}", json={"cursor_at": "2024-01-17T10:00:00Z"})
    assert p.status_code == 200, p.text
    return p.json()


def test_session_starts_blind_with_warm_up_and_stored_config(auth_client, mirror):
    s = create(auth_client)
    assert datetime.fromisoformat(s["cursor_at"]) == datetime(2024, 1, 17, 8, 30, tzinfo=UTC)  # quarter of the window
    assert s["currency"] == "USD" and s["config"]["simulator"] == "sim-1"
    assert s["config"]["slippage_price"] == "0.00002" and s["config"]["partial_fills"] is False
    bars = auth_client.get(f"/api/v1/backtests/{s['id']}/bars").json()["bars"]
    assert len(bars) == 30 and max(b["t"] for b in bars) + 60 <= ts(8, 30)


def test_bracket_trade_fills_by_the_rules_and_results_come_from_analytics(auth_client, mirror):
    st = play_winning_long(auth_client)
    sid = st["session"]["id"]
    entry, tp = st["fills"]
    # Entry: ask open at 08:30 (1.09010) + 0.2 pip slippage. Target: first minute whose bid high reaches 1.09100
    # is 09:19 (open 1.09095), so the limit fills at its price, with no slippage.
    assert (entry["kind"], D(entry["price"]), D(entry["commission"]), entry["t"]) == (
        "entry",
        D("1.09012"),
        D("3.5"),
        ts(8, 30),
    )
    assert (tp["kind"], D(tp["price"]), tp["t"], tp["ambiguous"]) == ("take_profit", D("1.091"), ts(9, 19), False)
    statuses = {o["kind"]: o["status"] for o in st["orders"]}
    assert statuses == {"entry": "filled", "take_profit": "filled", "stop_loss": "cancelled"}
    (t,) = st["trades"]
    # gross = (1.09100 - 1.09012) x 100,000 = 88; fees 7; risk = (1.09012 - 1.08900) x 100,000 = 112
    assert (D(t["gross_pnl"]), D(t["fees"]), D(t["net_pnl"]), D(t["r_multiple"])) == (D(88), D(7), D(81), D("0.7232"))
    res = auth_client.get(f"/api/v1/backtests/{sid}/results").json()
    assert D(res["balance"]) == D("10081.00") and D(res["return_pct"]) == D("0.0081")
    assert res["summary"]["closed_trades"] == 1 and D(res["summary"]["net_pnl"]) == D("81.00")
    assert "not evidence of future results" in res["disclaimer"]
    assert auth_client.get(f"/api/v1/backtests/{sid}/verify").json()["reproducible"] is True


def test_identical_actions_give_identical_results(auth_client, mirror):
    a, b = play_winning_long(auth_client), play_winning_long(auth_client)
    strip = lambda fs: [(f["kind"], f["t"], f["side"], f["quantity"], f["price"], f["commission"]) for f in fs]  # noqa: E731
    assert strip(a["fills"]) == strip(b["fills"]) and len(a["fills"]) == 2


def test_one_jump_can_fill_the_entry_and_its_target(auth_client, mirror):
    # Regression: the target order is created and filled within a single cursor move.
    sid = create(auth_client)["id"]
    assert order(auth_client, sid, quantity="100000", stop_loss="1.08900", take_profit="1.09100").status_code == 201
    st = auth_client.patch(f"/api/v1/backtests/{sid}", json={"cursor_at": "2024-01-17T10:00:00Z"}).json()
    assert [(f["kind"], f["t"]) for f in st["fills"]] == [("entry", ts(8, 30)), ("take_profit", ts(9, 19))]
    assert D(st["trades"][0]["net_pnl"]) == D(81)
    assert auth_client.get(f"/api/v1/backtests/{sid}/verify").json()["reproducible"] is True


def test_open_position_risk_sizing_cancel_and_finish(auth_client, mirror):
    s = create(auth_client)
    sid = s["id"]
    # Risk 50 with a stop 10 pips under the last ask close (1.09010): 50 / 0.0011 = 45,454 -> 45,000 units.
    r = order(auth_client, sid, risk_amount="50", stop_loss="1.08900")
    assert r.status_code == 201 and D(r.json()["order"]["quantity"]) == D(45000)
    limit = order(auth_client, sid, side="sell", type="limit", price="1.09500", quantity="10000").json()["order"]
    auth_client.post(f"/api/v1/backtests/{sid}/advance", json={"steps": 5})
    st = auth_client.get(f"/api/v1/backtests/{sid}").json()
    assert D(st["position"]) == D(45000) and st["open_pnl"] is not None
    # open P&L = 45,000 x (bid close 1.09000 - entry 1.09012) = -5.40
    assert D(st["open_pnl"]) == D("-5.40")
    assert auth_client.post(f"/api/v1/backtests/{sid}/orders/{limit['id']}/cancel").status_code == 200
    fin = auth_client.post(f"/api/v1/backtests/{sid}/finish", json={"flatten": True}).json()
    assert fin["session"]["status"] == "completed" and D(fin["position"]) == 0
    last = fin["fills"][-1]
    assert last["kind"] == "finish" and D(last["price"]) == D("1.08998")  # bid close - slippage
    assert {o["status"] for o in fin["orders"]} == {"filled", "cancelled"}
    assert auth_client.get(f"/api/v1/backtests/{sid}/verify").json()["reproducible"] is True
    assert order(auth_client, sid, quantity="1000").status_code == 409


def test_validation(auth_client, mirror):
    s = create(auth_client)
    sid = s["id"]
    assert order(auth_client, sid, quantity="1000", price="1.09").status_code == 422  # market takes no price
    assert order(auth_client, sid, type="limit", quantity="1000").status_code == 422
    bad = order(auth_client, sid, quantity="1000", stop_loss="1.0950")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_bracket"
    assert order(auth_client, sid, risk_amount="10").json()["error"]["code"] == "invalid_size"
    assert order(auth_client, sid).json()["error"]["code"] == "invalid_size"
    back = auth_client.patch(f"/api/v1/backtests/{sid}", json={"cursor_at": "2024-01-17T08:10:00Z"})
    assert back.status_code == 422 and back.json()["error"]["code"] == "cursor_backwards"
    body = {
        "symbol": "EURUSD",
        "start_at": "2024-01-17T08:00:00Z",
        "end_at": "2024-03-30T00:00:00Z",
        "starting_balance": "1",
    }
    assert auth_client.post("/api/v1/backtests", json=body).status_code == 422
    assert (
        auth_client.post(
            "/api/v1/backtests", json=body | {"symbol": "AAPL", "end_at": "2024-01-18T00:00:00Z"}
        ).status_code
        == 422
    )
    end = auth_client.patch(f"/api/v1/backtests/{sid}", json={"cursor_at": "2024-01-17T10:00:00Z"}).json()
    assert end["session"]["at_end"] is True
    assert order(auth_client, sid, quantity="1000").json()["error"]["code"] == "session_ended"


def test_backtests_are_owner_only_and_separate_from_real_trades(auth_client, other_client, mirror):
    st = play_winning_long(auth_client)
    sid = st["session"]["id"]
    oid = st["orders"][0]["id"]
    for method, url, body in [
        ("get", f"/api/v1/backtests/{sid}", None), ("get", f"/api/v1/backtests/{sid}/bars", None),
        ("post", f"/api/v1/backtests/{sid}/advance", {"steps": 1}), ("post", f"/api/v1/backtests/{sid}/orders", {"side": "buy", "quantity": "1"}),
        ("post", f"/api/v1/backtests/{sid}/orders/{oid}/cancel", None), ("post", f"/api/v1/backtests/{sid}/finish", {}),
        ("get", f"/api/v1/backtests/{sid}/results", None), ("get", f"/api/v1/backtests/{sid}/verify", None),
        ("patch", f"/api/v1/backtests/{sid}", {"notes": "x"}), ("delete", f"/api/v1/backtests/{sid}", None),
    ]:  # fmt: skip
        r = getattr(other_client, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    assert other_client.get("/api/v1/backtests").json() == []
    # Simulated work never appears among real trades or in the dashboard.
    assert auth_client.get("/api/v1/trades").json()["total"] == 0
    assert auth_client.get("/api/v1/analytics/dashboard").json()["summary"]["closed_trades"] == 0
    exp = auth_client.get("/api/v1/exports/me").json()
    assert len(exp["backtest_sessions"]) == 1 and len(exp["backtest_fills"]) == 2 and len(exp["backtest_trades"]) == 1
    listed = auth_client.get("/api/v1/backtests").json()
    assert listed[0]["closed_trades"] == 1 and D(listed[0]["net_pnl"]) == D(81)
    assert auth_client.delete(f"/api/v1/backtests/{sid}").status_code == 204


def test_notes_and_screenshots(auth_client, mirror):
    s = create(auth_client)
    sid = s["id"]
    r = auth_client.patch(f"/api/v1/backtests/{sid}", json={"notes": "Asian range was tight"})
    assert r.json()["session"]["notes"] == "Asian range was tight"
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    up = auth_client.post(f"/api/v1/backtests/{sid}/attachments", files={"file": ("s.png", png, "image/png")})
    assert up.status_code == 201
    (att,) = auth_client.get(f"/api/v1/backtests/{sid}/attachments").json()
    assert auth_client.get(f"/api/v1/attachments/{att['id']}/content").content == png


def test_verify_detects_a_tampered_fill(auth_client, mirror, db):
    from sqlalchemy import update

    from app.modules.backtesting.models import BacktestFill

    sid = play_winning_long(auth_client)["session"]["id"]
    db.execute(
        update(BacktestFill).where(BacktestFill.session_id == sid, BacktestFill.seq == 2).values(price=D("1.092"))
    )
    db.commit()
    v = auth_client.get(f"/api/v1/backtests/{sid}/verify").json()
    assert v["reproducible"] is False and len(v["mismatches"]) == 1

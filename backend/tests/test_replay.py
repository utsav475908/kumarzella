"""Replay sessions: blind mode never sends bars beyond the cursor; review mode shows the whole trade; save/resume."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from app.core.config import get_settings
from tests.helpers import all_trades, create_account, import_file
from tests.md_helpers import ask_of, write_day, write_eurusd_fixture

DAY2 = date(2024, 1, 17)


def iso(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def at(h, m):
    return datetime(2024, 1, 17, h, m, tzinfo=UTC)


def ts(h, m):
    return int(datetime(2024, 1, 17, h, m, tzinfo=UTC).timestamp())


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    write_eurusd_fixture(tmp_path)
    bars = {}
    price = D("1.09000")
    for minute in range(8 * 60, 13 * 60):
        o = price
        c = price + D("0.00005") * (1 if minute % 3 else -1)
        bars[f"{minute // 60:02d}:{minute % 60:02d}"] = (str(o), str(max(o, c) + D("0.00002")),
                                                       str(min(o, c) - D("0.00002")), str(c))  # fmt: skip
        price = c
    write_day(tmp_path, "EURUSD", DAY2, "bid", bars)
    write_day(tmp_path, "EURUSD", DAY2, "ask", ask_of(bars))
    s = get_settings()
    monkeypatch.setattr(s, "dukascopy_base_url", f"file://{tmp_path}")
    monkeypatch.setattr(s, "marketdata_provider", "dukascopy")
    return tmp_path


def blind(client, **kw):
    body = {"mode": "blind", "symbol": "EURUSD", "timeframe": "1m", "start_at": "2024-01-17T08:00:00Z",
            "end_at": "2024-01-17T13:00:00Z"} | kw  # fmt: skip
    r = client.post("/api/v1/replay/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_blind_reveals_only_bars_before_cursor(auth_client, mirror):
    s = blind(auth_client)
    assert iso(s["cursor_at"]) == at(9, 0)  # 60 warm-up bars of context
    r = auth_client.get(f"/api/v1/replay/sessions/{s['id']}/bars").json()
    assert len(r["bars"]) == 60 and r["markers"] == [] and r["overlay"] is None
    assert max(b["t"] for b in r["bars"]) + 60 <= ts(9, 0)

    adv = auth_client.post(f"/api/v1/replay/sessions/{s['id']}/advance", json={"steps": 5}).json()
    assert [b["t"] for b in adv["bars"]] == [ts(9, m) for m in range(5)]
    assert iso(adv["cursor_at"]) == at(9, 5) and adv["completed"] is False
    again = auth_client.get(f"/api/v1/replay/sessions/{s['id']}/bars").json()
    assert len(again["bars"]) == 65 and max(b["t"] for b in again["bars"]) == ts(9, 4)


def test_blind_higher_timeframe_never_sends_a_forming_bar(auth_client, mirror):
    s = blind(auth_client, timeframe="15m")
    r = auth_client.get(f"/api/v1/replay/sessions/{s['id']}/bars").json()
    cursor = int(iso(r["cursor_at"]).timestamp())
    assert cursor == ts(9, 15)  # warm-up is capped at a quarter of the five-hour window
    assert all(b["t"] + 900 <= cursor for b in r["bars"])
    adv = auth_client.post(f"/api/v1/replay/sessions/{s['id']}/advance", json={"steps": 1}).json()
    (bar,) = adv["bars"]
    assert bar["t"] == cursor and adv["cursor_at"] != r["cursor_at"]


def test_blind_seek_annotations_resume_and_completion(auth_client, mirror):
    s = blind(auth_client)
    sid = s["id"]
    early = auth_client.post(f"/api/v1/replay/sessions/{sid}/annotations",
                             json={"bar_time": "2024-01-17T10:00:00Z", "text": "future"})  # fmt: skip
    assert early.status_code == 422  # not revealed yet
    ok = auth_client.post(f"/api/v1/replay/sessions/{sid}/annotations",
                          json={"bar_time": "2024-01-17T08:30:00Z", "price": "1.0901", "text": "range low"})  # fmt: skip
    assert ok.status_code == 201
    p = auth_client.patch(f"/api/v1/replay/sessions/{sid}", json={"cursor_at": "2024-01-17T12:00:30Z", "speed": 8})
    assert iso(p.json()["cursor_at"]) == at(12, 0) and p.json()["speed"] == 8  # aligned to the timeframe
    resumed = auth_client.get(f"/api/v1/replay/sessions/{sid}").json()
    assert iso(resumed["cursor_at"]) == at(12, 0) and 0.79 < resumed["progress"] < 0.81
    done = auth_client.post(f"/api/v1/replay/sessions/{sid}/advance", json={"steps": 64}).json()
    assert len(done["bars"]) == 60 and done["completed"] and done["progress"] == 1.0
    notes = auth_client.get(f"/api/v1/replay/sessions/{sid}/annotations").json()
    assert [n["text"] for n in notes] == ["range low"]


def test_blind_validation(auth_client, mirror):
    base = {"mode": "blind", "symbol": "EURUSD", "start_at": "2024-01-17T08:00:00Z", "end_at": "2024-03-30T00:00:00Z"}
    assert auth_client.post("/api/v1/replay/sessions", json=base).status_code == 422  # too long
    assert auth_client.post("/api/v1/replay/sessions", json=base | {"symbol": "AAPL"}).status_code == 422
    assert auth_client.post("/api/v1/replay/sessions", json={"mode": "review"}).status_code == 422
    future = base | {"start_at": "2099-01-01T00:00:00Z", "end_at": "2099-01-02T00:00:00Z"}
    assert auth_client.post("/api/v1/replay/sessions", json=future).status_code == 422


def test_review_mode_shows_whole_trade_with_markers_and_overlay(auth_client, mirror):
    acct = create_account(auth_client, "FX")
    import_file(auth_client, acct["id"], "fixture_fx.csv", options={"timezone": "UTC"})
    (t,) = all_trades(auth_client)
    auth_client.patch(f"/api/v1/trades/{t['id']}", json={"planned_stop_price": "1.0895"})
    r = auth_client.post("/api/v1/replay/sessions", json={"mode": "review", "trade_id": t["id"]})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["cursor_at"] == s["start_at"]
    bars = auth_client.get(f"/api/v1/replay/sessions/{s['id']}/bars").json()
    assert len(bars["bars"]) == 10  # every cached bar in the window, including those after the cursor
    assert [m["side"] for m in bars["markers"]] == ["buy", "sell"]
    assert bars["overlay"]["planned_stop_price"] == "1.0895000000" and bars["overlay"]["direction"] == "long"


def test_replay_is_owner_only(auth_client, other_client, mirror):
    s = blind(auth_client)
    sid = s["id"]
    assert other_client.get(f"/api/v1/replay/sessions/{sid}").status_code == 404
    assert other_client.get(f"/api/v1/replay/sessions/{sid}/bars").status_code == 404
    assert other_client.post(f"/api/v1/replay/sessions/{sid}/advance", json={"steps": 1}).status_code == 404
    assert other_client.delete(f"/api/v1/replay/sessions/{sid}").status_code == 404
    assert other_client.get("/api/v1/replay/sessions").json() == []
    acct = create_account(auth_client, "FX")
    import_file(auth_client, acct["id"], "fixture_fx.csv", options={"timezone": "UTC"})
    (t,) = all_trades(auth_client)
    r = other_client.post("/api/v1/replay/sessions", json={"mode": "review", "trade_id": t["id"]})
    assert r.status_code == 404
    assert auth_client.delete(f"/api/v1/replay/sessions/{sid}").status_code == 204


def test_export_includes_replays_but_not_provider_candles(auth_client, mirror):
    s = blind(auth_client)
    auth_client.post(
        f"/api/v1/replay/sessions/{s['id']}/annotations", json={"bar_time": "2024-01-17T08:10:00Z", "text": "n"}
    )
    exp = auth_client.get("/api/v1/exports/me").json()
    assert [r["id"] for r in exp["replay_sessions"]] == [s["id"]] and len(exp["replay_annotations"]) == 1
    assert not any("candle" in k for k in exp)

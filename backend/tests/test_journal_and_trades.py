from decimal import Decimal as D

from tests.helpers import all_trades, create_account, import_file

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _manual(client, account_id, **kw):
    body = {
        "account_id": account_id,
        "symbol": "QQQ",
        "executions": [
            {
                "side": "buy",
                "quantity": "10",
                "price": "440",
                "commission": "0.5",
                "executed_at": "2024-05-01T14:00:00Z",
            },
            {
                "side": "sell",
                "quantity": "10",
                "price": "436",
                "commission": "0.5",
                "executed_at": "2024-05-01T15:00:00Z",
            },
        ],
        "planned_stop_price": "438",
        **kw,
    }
    return client.post("/api/v1/trades/manual", json=body)


def test_manual_trade_entry_computes_risk_and_r(auth_client):
    acct = create_account(auth_client)
    r = _manual(auth_client, acct["id"], note="Chased the open")
    assert r.status_code == 201, r.text
    (t,) = r.json()
    # gross (436-440)*10 = -40 ; net -41 ; risk (440-438)*10 = 20 ; R = -41/20 = -2.05
    assert t["origin"] == "manual" and D(t["net_pnl"]) == D("-41")
    assert D(t["initial_risk"]) == D("20") and D(t["r_multiple"]) == D("-2.05")
    detail = auth_client.get(f"/api/v1/trades/{t['id']}").json()
    assert detail["notes"][0]["body"] == "Chased the open"
    assert detail["executions"][0]["source_ref"] is None


def test_manual_trade_rejects_naive_timestamps(auth_client):
    acct = create_account(auth_client)
    body = {
        "account_id": acct["id"], "symbol": "QQQ",
        "executions": [{"side": "buy", "quantity": "1", "price": "1", "executed_at": "2024-05-01T14:00:00"}],
    }  # fmt: skip
    assert auth_client.post("/api/v1/trades/manual", json=body).status_code == 422


def test_imported_trades_cannot_be_deleted_but_manual_can(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    (imported,) = all_trades(auth_client)
    r = auth_client.delete(f"/api/v1/trades/{imported['id']}")
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_manual"
    (manual,) = _manual(auth_client, acct["id"]).json()
    assert auth_client.delete(f"/api/v1/trades/{manual['id']}").status_code == 204
    assert len(all_trades(auth_client)) == 1


def test_tags_playbook_and_filters(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    tag = auth_client.post("/api/v1/tags", json={"name": "FOMO", "category": "mistake"}).json()
    pb = auth_client.post("/api/v1/playbooks", json={"name": "Opening range breakout"}).json()
    aapl = next(t for t in all_trades(auth_client) if t["symbol"] == "AAPL")
    r = auth_client.patch(f"/api/v1/trades/{aapl['id']}", json={"tag_ids": [tag["id"]], "playbook_id": pb["id"]})
    assert r.status_code == 200
    assert r.json()["tags"][0]["name"] == "FOMO" and r.json()["playbook_name"] == "Opening range breakout"
    assert [t["symbol"] for t in all_trades(auth_client, tag_id=tag["id"])] == ["AAPL"]
    assert [t["symbol"] for t in all_trades(auth_client, playbook_id=pb["id"])] == ["AAPL"]
    assert len(all_trades(auth_client, playbook_id="none")) == 5
    assert {t["symbol"] for t in all_trades(auth_client, direction="short")} == {"TSLA", "ESH4"}
    assert [t["symbol"] for t in all_trades(auth_client, asset_class="future")] == ["ESH4", "ESH4"]
    assert len(all_trades(auth_client, date_from="2024-03-06", date_to="2024-03-06")) == 2
    assert [t["symbol"] for t in all_trades(auth_client, outcome="loss")] == ["TSLA"]
    assert len(all_trades(auth_client, q="sl")) == 1
    tags = auth_client.get("/api/v1/tags").json()
    assert tags[0]["trade_count"] == 1


def test_pagination_and_sorting(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    p1 = auth_client.get("/api/v1/trades", params={"page_size": 4, "sort": "net_pnl", "order": "desc"}).json()
    assert p1["total"] == 6 and len(p1["items"]) == 4
    assert D(p1["items"][0]["net_pnl"]) == D("195.8")
    p2 = auth_client.get(
        "/api/v1/trades", params={"page_size": 4, "page": 2, "sort": "net_pnl", "order": "desc"}
    ).json()
    assert len(p2["items"]) == 2 and D(p2["items"][-1]["net_pnl"]) == D("-202")


def test_trade_detail_navigation_and_audit(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    trades = all_trades(auth_client)
    mid = auth_client.get(f"/api/v1/trades/{trades[1]['id']}").json()
    assert mid["prev_trade_id"] == trades[0]["id"] and mid["next_trade_id"] == trades[2]["id"]
    auth_client.patch(f"/api/v1/trades/{trades[1]['id']}", json={"rating": 4})
    mid = auth_client.get(f"/api/v1/trades/{trades[1]['id']}").json()
    assert mid["audit"][0]["action"] == "trade.updated" and mid["audit"][0]["data"] == {"fields": ["rating"]}


def test_notes_and_day_notes(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    (t,) = all_trades(auth_client)
    n = auth_client.post(f"/api/v1/trades/{t['id']}/notes", json={"body": "first"}).json()
    auth_client.patch(f"/api/v1/trades/{t['id']}/notes/{n['id']}", json={"body": "edited"})
    assert auth_client.put("/api/v1/day-notes/2024-04-01", json={"body": "Choppy open"}).status_code == 200
    d = auth_client.get(f"/api/v1/trades/{t['id']}").json()
    assert d["notes"][0]["body"] == "edited" and d["day_note"] == "Choppy open"
    assert auth_client.delete(f"/api/v1/trades/{t['id']}/notes/{n['id']}").status_code == 204
    assert auth_client.post(f"/api/v1/trades/{t['id']}/notes", json={"body": ""}).status_code == 422


def test_attachments_validate_magic_bytes(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    (t,) = all_trades(auth_client)
    bad = auth_client.post(
        f"/api/v1/trades/{t['id']}/attachments", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unsupported_file_type"
    ok = auth_client.post(
        f"/api/v1/trades/{t['id']}/attachments", files={"file": ("../../chart.png", PNG, "text/plain")}
    )
    assert ok.status_code == 201
    att = ok.json()
    assert att["content_type"] == "image/png" and att["filename"] == "chart.png"
    got = auth_client.get(f"/api/v1/attachments/{att['id']}/content")
    assert got.status_code == 200 and got.content == PNG
    assert auth_client.delete(f"/api/v1/attachments/{att['id']}").status_code == 204


def test_accounting_policy_change_rebuilds(auth_client):
    acct = create_account(auth_client)
    body = {
        "account_id": acct["id"], "symbol": "IWM",
        "executions": [
            {"side": "buy", "quantity": "100", "price": "10", "executed_at": "2024-05-01T14:00:00Z"},
            {"side": "buy", "quantity": "100", "price": "12", "executed_at": "2024-05-01T14:01:00Z"},
            {"side": "sell", "quantity": "50", "price": "13", "executed_at": "2024-05-01T14:02:00Z"},
        ],
    }  # fmt: skip
    (t,) = auth_client.post("/api/v1/trades/manual", json=body).json()
    assert D(t["gross_pnl"]) == D("100")  # average cost
    auth_client.patch(f"/api/v1/accounts/{acct['id']}", json={"accounting_policy": "fifo"})
    (t2,) = all_trades(auth_client)
    assert t2["id"] == t["id"] and D(t2["gross_pnl"]) == D("150")


def test_cash_transactions_are_separate(auth_client):
    acct = create_account(auth_client, starting_balance="10000")
    r = auth_client.post(
        f"/api/v1/accounts/{acct['id']}/cash-transactions",
        json={"kind": "deposit", "amount": "5000", "occurred_at": "2024-03-01T00:00:00Z"},
    )
    assert r.status_code == 201 and r.json()["currency"] == "USD"
    assert all_trades(auth_client) == []


def test_export_contains_only_own_data(auth_client, other_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    create_account(other_client, name="Other acct")
    data = auth_client.get("/api/v1/exports/me").json()
    assert len(data["executions"]) == 3 and len(data["accounts"]) == 1
    assert "password_hash" not in data["user"]


def test_delete_account_requires_confirmation(auth_client):
    acct = create_account(auth_client, name="Old")
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    r = auth_client.delete(f"/api/v1/accounts/{acct['id']}", params={"confirm_name": "nope"})
    assert r.status_code == 409
    assert auth_client.delete(f"/api/v1/accounts/{acct['id']}", params={"confirm_name": "Old"}).status_code == 204
    assert all_trades(auth_client) == []

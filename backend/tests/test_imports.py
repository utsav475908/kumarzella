from decimal import Decimal as D

from tests.helpers import all_trades, create_account, expected, fixture_bytes, import_file, upload


def test_upload_detects_generic_preset_and_suggests_mapping(auth_client):
    acct = create_account(auth_client)
    r = upload(auth_client, acct["id"], "fixture_a.csv")
    assert r.status_code == 201
    body = r.json()
    assert body["detected_preset"] == "generic"
    assert body["suggested_mapping"]["quantity"] == "Quantity"
    assert body["total_rows"] == 14 and body["status"] == "uploaded"
    assert len(body["sample_rows"]) == 10


def test_preview_reports_rejected_and_duplicate_rows(auth_client):
    acct = create_account(auth_client)
    job = upload(auth_client, acct["id"], "fixture_a.csv").json()
    pv = auth_client.post(f"/api/v1/imports/{job['id']}/preview", json={"mapping": job["suggested_mapping"]}).json()
    exp = expected("fixture_a_expected.json")["rows"]
    assert pv["job"]["valid_rows"] == exp["valid"]
    assert pv["job"]["rejected_rows"] == exp["rejected"]
    assert pv["job"]["duplicate_rows"] == exp["duplicate"]
    rejected = [r for r in pv["rows"] if r["status"] == "rejected"]
    assert rejected[0]["row_number"] == 11 and "quantity" in rejected[0]["errors"][0]
    dup = [r for r in pv["rows"] if r["status"] == "duplicate"]
    assert dup[0]["row_number"] == 12
    # Nothing is written to executions or trades until commit.
    assert all_trades(auth_client) == []


def test_commit_reconstructs_expected_trades(auth_client):
    acct = create_account(auth_client)
    res = import_file(auth_client, acct["id"], "fixture_a.csv")
    assert res["commit"].status_code == 200
    job = res["commit"].json()
    assert job["status"] == "completed" and job["imported_rows"] == 12
    assert job["summary"]["trades_created"] == 6

    trades = all_trades(auth_client)
    exp = expected("fixture_a_expected.json")["trades"]
    got = [
        {k: t[k] for k in ("symbol", "direction", "status", "session_date", "holding_seconds")}
        | {k: D(t[k]) for k in ("gross_pnl", "fees", "net_pnl")}
        for t in trades
    ]
    want = [{**e, **{k: D(e[k]) for k in ("gross_pnl", "fees", "net_pnl")}} for e in exp]
    assert sorted(got, key=lambda x: (x["session_date"], x["symbol"], x["direction"])) == sorted(
        want, key=lambda x: (x["session_date"], x["symbol"], x["direction"])
    )


def test_reimport_same_file_is_idempotent(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    before = all_trades(auth_client)
    res = import_file(auth_client, acct["id"], "fixture_a.csv")
    assert res["preview"]["job"]["valid_rows"] == 0
    assert res["preview"]["job"]["duplicate_rows"] == 13
    assert res["commit"].status_code == 422
    assert res["commit"].json()["error"]["code"] == "nothing_to_import"
    assert all_trades(auth_client) == before


def test_reimport_without_execution_ids_uses_fingerprints(auth_client):
    acct = create_account(auth_client)
    first = import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    assert first["commit"].json()["imported_rows"] == 3  # two identical fills both kept
    (t,) = all_trades(auth_client)
    assert D(t["gross_pnl"]) == D("20") and D(t["net_pnl"]) == D("19.6")
    again = import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    assert again["preview"]["job"]["duplicate_rows"] == 3


def test_overlapping_import_closes_open_trade_and_keeps_journal(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    msft = next(t for t in all_trades(auth_client) if t["symbol"] == "MSFT")
    assert msft["status"] == "open"
    auth_client.post(f"/api/v1/trades/{msft['id']}/notes", json={"body": "Breakout entry"})
    auth_client.patch(f"/api/v1/trades/{msft['id']}", json={"planned_stop_price": "395"})

    res = import_file(auth_client, acct["id"], "fixture_b_overlap.csv")
    assert res["preview"]["job"]["duplicate_rows"] == 1 and res["preview"]["job"]["valid_rows"] == 1
    after = auth_client.get(f"/api/v1/trades/{msft['id']}").json()
    assert after["status"] == "closed" and D(after["net_pnl"]) == D("50")
    assert after["notes"][0]["body"] == "Breakout entry"
    # risk = (400 - 395) * 10 = 50 ; R = 50 / 50 = 1
    assert D(after["initial_risk"]) == D("50") and D(after["r_multiple"]) == D("1")


def test_signed_quantity_preset_with_negative_commissions(auth_client):
    acct = create_account(auth_client)
    up = upload(auth_client, acct["id"], "fixture_signed_qty.csv").json()
    assert up["detected_preset"] == "signed_quantity"
    res = import_file(
        auth_client, acct["id"], "fixture_signed_qty.csv",
        mapping=up["suggested_mapping"], options={"side_from_quantity_sign": True},
    )  # fmt: skip
    assert res["commit"].json()["status"] == "completed"
    spy, mnq = all_trades(auth_client)
    # SPY: (511.35 - 510.10) * 200 = 250 ; fees 2 -> 248
    assert spy["symbol"] == "SPY" and D(spy["net_pnl"]) == D("248")
    # MNQ short: (18200.25 - 18190.75) * 3 * 2 = 57 ; fees 3.72 -> 53.28
    assert mnq["asset_class"] == "future" and mnq["direction"] == "short" and D(mnq["net_pnl"]) == D("53.28")


def test_utc_offset_timestamps_and_session_dates(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_no_ids.csv")
    (t,) = all_trades(auth_client)
    assert t["opened_at"].startswith("2024-04-01T13:31:00")
    assert t["session_date"] == "2024-04-01" and t["entry_session"] == "regular"  # 09:31 EDT


def test_rejects_non_csv_and_binary_uploads(auth_client):
    acct = create_account(auth_client)
    r = upload(auth_client, acct["id"], "x.exe", b"MZ\x00\x00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_file_type"
    r = upload(auth_client, acct["id"], "x.csv", b"\x00\x01\x02")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_csv"
    r = upload(auth_client, acct["id"], "x.csv", b"a,b\n")
    assert r.status_code == 422


def test_preview_validates_mapping_columns(auth_client):
    acct = create_account(auth_client)
    job = upload(auth_client, acct["id"], "fixture_a.csv").json()
    bad = {**job["suggested_mapping"], "price": "Nope"}
    r = auth_client.post(f"/api/v1/imports/{job['id']}/preview", json={"mapping": bad})
    assert r.status_code == 422 and r.json()["error"]["details"]["columns"] == ["Nope"]


def test_commit_requires_preview(auth_client):
    acct = create_account(auth_client)
    job = upload(auth_client, acct["id"], "fixture_a.csv").json()
    r = auth_client.post(f"/api/v1/imports/{job['id']}/commit")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_previewed"


def test_raw_records_traceable_from_trade(auth_client):
    acct = create_account(auth_client)
    import_file(auth_client, acct["id"], "fixture_a.csv")
    es = [t for t in all_trades(auth_client) if t["symbol"] == "ESH4"]
    detail = auth_client.get(f"/api/v1/trades/{es[0]['id']}").json()
    legs = detail["executions"]
    assert [leg["role"] for leg in legs] == ["open", "close"]
    reversal = legs[1]
    assert reversal["shared_with_other_trade"] is True
    assert D(reversal["allocated_quantity"]) == D("1") and D(reversal["quantity"]) == D("2")
    assert reversal["source_ref"]["row_number"] == 8
    assert reversal["source_ref"]["raw"]["Exec ID"] == "E2"
    assert reversal["source_ref"]["filename"] == "fixture_a.csv"


def test_failed_commit_is_atomic(auth_client, monkeypatch):
    from app.modules.imports import service

    acct = create_account(auth_client)
    job = upload(auth_client, acct["id"], "fixture_a.csv").json()
    auth_client.post(f"/api/v1/imports/{job['id']}/preview", json={"mapping": job["suggested_mapping"]})

    def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(service, "rebuild_account", boom)
    r = auth_client.post(f"/api/v1/imports/{job['id']}/commit")
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert all_trades(auth_client) == []
    records = auth_client.get(f"/api/v1/imports/{job['id']}/records", params={"status": "imported"}).json()
    assert records["total"] == 0
    _ = fixture_bytes

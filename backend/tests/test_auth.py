from tests.conftest import make_client, register


def test_register_login_logout_flow(client):
    user = register(client)
    assert user["email"] == "trader@example.com"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["id"] == user["id"]

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    r = client.post("/api/v1/auth/login", json={"email": "TRADER@example.com", "password": "correct-horse-9"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_session_cookie_is_httponly(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "correct-horse-9", "display_name": "A"},
    )
    cookie_headers = r.headers.get_list("set-cookie")
    session = next(h for h in cookie_headers if h.startswith("el_session="))
    assert "HttpOnly" in session and "SameSite=lax" in session


def test_duplicate_email_rejected_case_insensitive(client):
    register(client)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "Trader@Example.com", "password": "correct-horse-9", "display_name": "X"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_wrong_password_and_unknown_email_look_identical(client):
    register(client)
    client.post("/api/v1/auth/logout")
    a = client.post("/api/v1/auth/login", json={"email": "trader@example.com", "password": "nope-nope-1"})
    b = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_weak_password_rejected(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "w@example.com", "password": "abcdefghijk", "display_name": "W"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_csrf_required_for_unsafe_methods(app):
    from fastapi.testclient import TestClient

    raw = TestClient(app)
    r = raw.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "whatever-1"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


def test_login_rate_limited(client):
    register(client)
    client.post("/api/v1/auth/logout")
    codes = [
        client.post(
            "/api/v1/auth/login", json={"email": "trader@example.com", "password": "bad-password-1"}
        ).status_code
        for _ in range(12)
    ]
    assert codes[-1] == 429


def test_sessions_list_and_revoke(app):
    c1 = make_client(app)
    register(c1)
    c2 = make_client(app)
    c2.post("/api/v1/auth/login", json={"email": "trader@example.com", "password": "correct-horse-9"})
    sessions = c1.get("/api/v1/auth/sessions").json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert c1.delete(f"/api/v1/auth/sessions/{other['id']}").status_code == 204
    assert c2.get("/api/v1/auth/me").status_code == 401


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_openapi_documents_v1(client):
    spec = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/auth/login" in spec["paths"]

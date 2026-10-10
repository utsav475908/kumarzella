import os

os.environ.setdefault("EL_ENVIRONMENT", "test")
os.environ.setdefault("EL_DATABASE_URL", "postgresql+psycopg://tj:tj@localhost:5432/tradejournal_test")
os.environ.setdefault("EL_LOG_JSON", "false")
os.environ.setdefault("EL_LOG_LEVEL", "WARNING")
os.environ.setdefault("EL_JOBS_EAGER", "true")
os.environ.setdefault("EL_STORAGE_LOCAL_PATH", "/tmp/el-test-storage")

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core import ratelimit  # noqa: E402
from app.core.db import Base, SessionLocal, get_engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    yield
    eng = get_engine()
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    ratelimit.reset_local()
    try:
        r = ratelimit._redis()
        if r is not None:
            for k in r.scan_iter("rl:*"):
                r.delete(k)
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


class ApiClient(TestClient):
    """TestClient that performs the CSRF double-submit automatically."""

    def request(self, method, url, *args, **kwargs):
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            token = self.cookies.get("el_csrf")
            if token is None and url != "/api/v1/auth/csrf":
                super().request("GET", "/api/v1/auth/csrf")
                token = self.cookies.get("el_csrf")
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", token or "")
            kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


def make_client(app) -> ApiClient:
    return ApiClient(app, base_url="http://testserver")


@pytest.fixture
def client(app):
    return make_client(app)


def register(client, email="trader@example.com", password="correct-horse-9", name="Trader"):
    r = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "display_name": name}
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def auth_client(app):
    c = make_client(app)
    register(c)
    return c


@pytest.fixture
def other_client(app):
    c = make_client(app)
    register(c, email="other@example.com", name="Other")
    return c

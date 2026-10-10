from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.csrf import CSRFMiddleware
from app.core.db import SessionLocal
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.routers import api_routers


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(
        title=f"{s.app_name} API",
        version="0.3.0",
        description="Trading journal and analytics API. All financial figures are computed server-side.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    v1 = APIRouter(prefix="/api/v1")
    for r in api_routers():
        v1.include_router(r)
    app.include_router(v1)

    @app.get("/healthz", tags=["ops"])
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz():
        checks = {}
        try:
            with SessionLocal() as db:
                db.execute(text("select 1"))
            checks["database"] = "ok"
        except Exception:  # noqa: BLE001
            checks["database"] = "error"
        try:
            from app.core.ratelimit import _redis

            r = _redis()
            checks["redis"] = "ok" if r is not None and r.ping() else "error"
        except Exception:  # noqa: BLE001
            checks["redis"] = "error"
        ok = all(v == "ok" for v in checks.values())
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **checks}
        )

    return app


app = create_app()

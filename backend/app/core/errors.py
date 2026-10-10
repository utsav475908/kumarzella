"""Consistent error envelope: {"error": {"code", "message", "details"}}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import log


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self, message: str, *, details: Any = None, code: str | None = None, status: int | None = None
    ):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code
        if status:
            self.status_code = status


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=_body("validation_failed", "Request validation failed", details)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
        return JSONResponse(status_code=500, content=_body("internal_error", "An unexpected error occurred"))

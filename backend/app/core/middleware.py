import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import log
from app.core.request_context import current_ip, current_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        current_request_id.set(rid[:64])
        current_ip.set(request.client.host if request.client else None)
        structlog.contextvars.bind_contextvars(request_id=rid[:64])
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["x-request-id"] = rid[:64]
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "same-origin"
        # Only path and status are logged; query strings and bodies may contain financial data.
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=elapsed_ms,
        )
        structlog.contextvars.clear_contextvars()
        return response

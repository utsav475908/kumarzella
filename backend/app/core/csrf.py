"""Double-submit CSRF protection. Every unsafe request must echo the el_csrf cookie in X-CSRF-Token.

Combined with SameSite=Lax session cookies this blocks cross-site form posts and fetches.
"""

import secrets

from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.security import constant_time_equals

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS = {"/api/v1/auth/csrf"}


def issue_csrf_cookie(response: Response) -> str:
    s = get_settings()
    token = secrets.token_urlsafe(24)
    response.set_cookie(
        s.csrf_cookie_name, token, httponly=False, secure=s.cookie_secure, samesite="lax", path="/"
    )
    return token


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and (request.url.path not in EXEMPT_PATHS)
        ):
            s = get_settings()
            cookie = request.cookies.get(s.csrf_cookie_name)
            header = request.headers.get("x-csrf-token")
            if not cookie or not header or not constant_time_equals(cookie, header):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "csrf_failed",
                            "message": "Missing or invalid CSRF token",
                            "details": None,
                        }
                    },
                )
        return await call_next(request)

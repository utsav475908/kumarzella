from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.config import get_settings
from app.core.csrf import issue_csrf_cookie
from app.core.db import get_db
from app.core.deps import get_current_session, get_current_user
from app.core.errors import NotFound
from app.modules.auth import service
from app.modules.auth.models import User, UserSession
from app.modules.auth.schemas import LoginIn, RegisterIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/csrf", summary="Issue a CSRF token cookie (double-submit pattern)")
def csrf(response: Response) -> dict:
    return {"csrf_token": issue_csrf_cookie(response)}


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ratelimit.hit(f"register:{_client_ip(request)}", s.login_rate_limit, s.login_rate_window_seconds)
    user = service.register(db, data)
    _set_session_cookie(
        response, service.create_session(db, user, _client_ip(request), request.headers.get("user-agent"))
    )
    issue_csrf_cookie(response)
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    ip = _client_ip(request)
    ratelimit.hit(f"login:ip:{ip}", s.login_rate_limit, s.login_rate_window_seconds)
    ratelimit.hit(f"login:email:{data.email.lower()}", s.login_rate_limit, s.login_rate_window_seconds)
    user = service.authenticate(db, data)
    _set_session_cookie(response, service.create_session(db, user, ip, request.headers.get("user-agent")))
    issue_csrf_cookie(response)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response, sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)):
    service.revoke_session(db, sess)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/sessions", response_model=list[SessionOut])
def sessions(
    user: User = Depends(get_current_user),
    current: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    now = datetime.now(UTC)
    rows = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
        .order_by(UserSession.created_at.desc())
    )
    out = []
    for r in rows:
        item = SessionOut.model_validate(r)
        item.current = r.id == current.id
        out.append(item)
    return out


@router.delete("/sessions/{session_id}", status_code=204)
def revoke(session_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.get(UserSession, session_id)
    if sess is None or sess.user_id != user.id:
        raise NotFound("Session not found")
    service.revoke_session(db, sess)
    return Response(status_code=204)

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import ratelimit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.security import token_hash
from app.modules.accounts.models import Account
from app.modules.auth.models import User, UserSession


def get_current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    if not token:
        raise Unauthorized("Not signed in")
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
    now = datetime.now(UTC)
    if sess is None or sess.revoked_at is not None or sess.expires_at <= now:
        raise Unauthorized("Session expired or invalid")
    if sess.last_seen_at is None or now - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = now
        db.commit()
    return sess


def get_current_user(sess: UserSession = Depends(get_current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Account disabled")
    s = get_settings()
    ratelimit.hit(f"user:{user.id}", s.api_rate_limit, s.api_rate_window_seconds)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise Forbidden("Admin role required")
    return user


def owned_account(db: Session, user: User, account_id: UUID) -> Account:
    """Ownership check. Returns 404 (not 403) for other users' accounts to avoid leaking existence."""
    acct = db.get(Account, account_id)
    if acct is None or acct.user_id != user.id:
        raise NotFound("Account not found")
    return acct

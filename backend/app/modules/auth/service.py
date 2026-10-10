from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Unauthorized
from app.core.security import DUMMY_HASH, hash_password, needs_rehash, new_token, token_hash, verify_password
from app.modules.audit import service as audit
from app.modules.auth.models import User, UserSession
from app.modules.auth.schemas import LoginIn, RegisterIn


def register(db: Session, data: RegisterIn) -> User:
    email = data.email.strip().lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise Conflict("An account with this email already exists", code="email_taken")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        display_name=data.display_name.strip(),
        timezone=data.timezone,
    )
    db.add(user)
    db.flush()
    audit.record(db, user_id=user.id, action="user.registered", entity_type="user", entity_id=user.id)
    db.commit()
    return user


def authenticate(db: Session, data: LoginIn) -> User:
    email = data.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        verify_password(DUMMY_HASH, data.password)
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if not verify_password(user.password_hash, data.password) or not user.is_active or user.deleted_at:
        audit.record(db, user_id=user.id, action="auth.login_failed", entity_type="user", entity_id=user.id)
        db.commit()
        raise Unauthorized("Invalid email or password", code="invalid_credentials")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    return user


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> str:
    token = new_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(token),
            created_at=now,
            expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
            last_seen_at=now,
            ip=ip,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    audit.record(db, user_id=user.id, action="auth.login", entity_type="user", entity_id=user.id)
    db.commit()
    return token


def revoke_session(db: Session, sess: UserSession) -> None:
    sess.revoked_at = datetime.now(UTC)
    audit.record(db, user_id=sess.user_id, action="auth.logout", entity_type="user", entity_id=sess.user_id)
    db.commit()

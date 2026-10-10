from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.request_context import current_ip, current_request_id
from app.modules.audit.models import AuditEvent


def record(
    db: Session,
    *,
    user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    data: dict | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction. Callers commit."""
    ev = AuditEvent(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip=current_ip.get(),
        request_id=current_request_id.get(),
        data=data,
    )
    db.add(ev)
    return ev


def list_for_entity(db: Session, user_id: UUID, entity_type: str, entity_id: UUID) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.user_id == user_id,
                AuditEvent.entity_type == entity_type,
                AuditEvent.entity_id == entity_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(200)
        )
    )

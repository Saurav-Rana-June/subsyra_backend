from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from src.audit_logs.models import AuditLogModel


def record_audit_log(
    db: Session,
    action: str,
    target_type: str,
    target_id: Optional[int] = None,
    user_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLogModel:
    """
    Persists an audit log entry tracking administrative or customer activity.
    """
    log_entry = AuditLogModel(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
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
    Persists an audit log entry tracking administrative, system, or customer actions.

    :param db: SQLAlchemy Session
    :param action: Short identifier of the action (e.g. CANCEL_SUBSCRIPTION, ISSUE_REFUND)
    :param target_type: Entity category (e.g. SUBSCRIPTION, PAYMENT, PLAN)
    :param target_id: ID of the primary entity modified
    :param user_id: ID of the actor initiating the action (or None for system events)
    :param details: Key-value context dictionary capturing metadata, old vs new state, etc.
    :return: Persisted AuditLogModel instance
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


def query_audit_logs(
    db: Session,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[AuditLogModel], int]:
    """
    Retrieves filtered audit logs with pagination and total match count.
    """
    query = db.query(AuditLogModel)

    if action:
        query = query.filter(AuditLogModel.action == action)
    if target_type:
        query = query.filter(AuditLogModel.target_type == target_type)
    if user_id:
        query = query.filter(AuditLogModel.user_id == user_id)
    if start_date:
        query = query.filter(AuditLogModel.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLogModel.created_at <= end_date)

    total_count = query.count()
    logs = (
        query.order_by(AuditLogModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return logs, total_count

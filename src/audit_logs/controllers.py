from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import status
import math

from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.audit_logs.services import query_audit_logs
from src.audit_logs.dtos import AuditLogReadSchema


def list_audit_logs(
    db: Session,
    user: UserModel,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
) -> ApiResponse:
    """
    Admin-only controller to retrieve paginated, filtered audit trail logs.
    """
    # 1. RBAC Check: Only Admins can inspect system audit logs
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators have permission to access audit logs.",
        )

    # 2. Sanitize pagination parameters
    safe_page = max(1, page)
    safe_limit = min(max(1, page_size), 100)
    offset = (safe_page - 1) * safe_limit

    # 3. Query audit records
    logs, total_count = query_audit_logs(
        db=db,
        action=action,
        target_type=target_type,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        limit=safe_limit,
        offset=offset,
    )

    serialized_logs = [
        AuditLogReadSchema.model_validate(log).model_dump() for log in logs
    ]
    total_pages = math.ceil(total_count / safe_limit) if total_count > 0 else 1

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Audit logs fetched successfully.",
        data={
            "logs": serialized_logs,
            "total_count": total_count,
            "page": safe_page,
            "page_size": safe_limit,
            "total_pages": total_pages,
        },
    )

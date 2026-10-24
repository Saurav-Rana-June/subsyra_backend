from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.audit_logs import controllers

audit_log_routes = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@audit_log_routes.get("", status_code=status.HTTP_200_OK)
def get_audit_logs(
    action: Optional[str] = Query(default=None, description="Filter by action name"),
    target_type: Optional[str] = Query(
        default=None, description="Filter by target type (SUBSCRIPTION, PAYMENT, etc.)"
    ),
    user_id: Optional[int] = Query(
        default=None, description="Filter by user / actor ID"
    ),
    start_date: Optional[datetime] = Query(
        default=None, description="Filter events on or after this ISO timestamp"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="Filter events on or before this ISO timestamp"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user

    return controllers.list_audit_logs(
        db=db,
        user=user,
        action=action,
        target_type=target_type,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

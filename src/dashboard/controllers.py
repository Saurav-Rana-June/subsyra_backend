from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import status

from src.utils.responses import ApiResponse
from src.users.models import UserModel
from src.dashboard import services


def get_dashboard_data(
    db: Session,
    user: UserModel,
    period: str = "Last 30 Days",
    plan_filter: str = "Plan",
    status_filter: str = "All",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Unified Dashboard Endpoint Controller.
    
    Delegates to services.get_dashboard_metrics to execute live database queries
    for both ADMIN and CUSTOMER roles.
    """
    data = services.get_dashboard_metrics(
        db=db,
        user=user,
        period=period,
        plan_filter=plan_filter,
        status_filter=status_filter,
        start_date=start_date,
        end_date=end_date,
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Dashboard data retrieved successfully",
        data=data.model_dump(),
    )

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.dashboard import controllers

dashboard_routes = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@dashboard_routes.get("", status_code=status.HTTP_200_OK)
def get_dashboard(
    period: Optional[str] = Query(
        default="Last 30 Days",
        description="Selected dashboard time window ('Last 7 Days', 'Last 30 Days', 'Last 90 Days', 'This Year', 'All Time')"
    ),
    plan_filter: Optional[str] = Query(
        default="Plan",
        description="Selected plan name filter for subscription summary table"
    ),
    status_filter: Optional[str] = Query(
        default="All",
        description="Selected status filter for status distribution chart"
    ),
    start_date: Optional[datetime] = Query(
        default=None,
        description="Optional custom range start date (ISO-8601)"
    ),
    end_date: Optional[datetime] = Query(
        default=None,
        description="Optional custom range end date (ISO-8601)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    """
    Get aggregated dashboard data tailored to the authenticated user's role.
    
    Returns:
    - **Admin Persona**: Executive financial KPIs (MRR, Active Subscriptions, Churn, Overdue Invoices),
      all-customer subscription table, and subscription status distribution chart.
    - **Customer Persona**: Active plan hero badge with next billing date/amount, personal subscription metrics,
      and user subscription records.
    """
    if isinstance(user, ApiResponse):
        return user

    return controllers.get_dashboard_data(
        db=db,
        user=user,
        period=period,
        plan_filter=plan_filter,
        status_filter=status_filter,
        start_date=start_date,
        end_date=end_date,
    )


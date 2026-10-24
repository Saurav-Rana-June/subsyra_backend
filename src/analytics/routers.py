from datetime import datetime
from typing import Optional, Literal
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.analytics import controllers

analytics_routes = APIRouter(prefix="/analytics", tags=["Analytics & Reporting"])


@analytics_routes.get("/overview", status_code=status.HTTP_200_OK)
def get_overview(
    start_date: Optional[datetime] = Query(
        default=None, description="Start date (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="End date (ISO format)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_overview_kpis(
        db=db, user=user, start_date=start_date, end_date=end_date
    )


@analytics_routes.get("/subscriptions", status_code=status.HTTP_200_OK)
def get_subscriptions(
    start_date: Optional[datetime] = Query(
        default=None, description="Start date (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="End date (ISO format)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_subscription_metrics(
        db=db, user=user, start_date=start_date, end_date=end_date
    )


@analytics_routes.get("/revenue", status_code=status.HTTP_200_OK)
def get_revenue(
    group_by: Literal["daily", "monthly", "yearly"] = Query(
        default="daily", description="Time aggregation bucket"
    ),
    start_date: Optional[datetime] = Query(
        default=None, description="Start date (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="End date (ISO format)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_revenue_metrics(
        db=db,
        user=user,
        group_by=group_by,
        start_date=start_date,
        end_date=end_date,
    )


@analytics_routes.get("/churn", status_code=status.HTTP_200_OK)
def get_churn(
    start_date: Optional[datetime] = Query(
        default=None, description="Start date (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="End date (ISO format)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_churn_metrics(
        db=db, user=user, start_date=start_date, end_date=end_date
    )


@analytics_routes.get("/payments", status_code=status.HTTP_200_OK)
def get_payments(
    start_date: Optional[datetime] = Query(
        default=None, description="Start date (ISO format)"
    ),
    end_date: Optional[datetime] = Query(
        default=None, description="End date (ISO format)"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_payment_metrics(
        db=db, user=user, start_date=start_date, end_date=end_date
    )

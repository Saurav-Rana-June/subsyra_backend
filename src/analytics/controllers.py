from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import status

from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.analytics import services
from src.analytics.dtos import (
    OverviewMetricsSchema,
    SubscriptionAnalyticsSchema,
    RevenueReportSchema,
    ChurnAnalyticsSchema,
    PaymentAnalyticsSchema,
)


def _resolve_date_range(
    start_date: Optional[datetime], end_date: Optional[datetime]
) -> tuple[datetime, datetime]:
    """
    Normalizes query date range, defaulting to the past 30 days if omitted.
    """
    now = datetime.now(timezone.utc)
    resolved_end = end_date or now
    resolved_start = start_date or (resolved_end - timedelta(days=30))
    return resolved_start, resolved_end


def get_overview_kpis(
    db: Session,
    user: UserModel,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Admin endpoint returning high-level financial and customer health KPIs.
    """
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can access financial analytics.",
        )

    s_date, e_date = _resolve_date_range(start_date, end_date)
    data = services.get_overview_analytics(db, s_date, e_date)
    serialized = OverviewMetricsSchema.model_validate(data).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Overview KPIs calculated successfully.",
        data=serialized,
    )


def get_subscription_metrics(
    db: Session,
    user: UserModel,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Admin endpoint returning subscription distribution by status and plan tiers.
    """
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can access subscription analytics.",
        )

    s_date, e_date = _resolve_date_range(start_date, end_date)
    data = services.get_subscription_analytics(db, s_date, e_date)
    serialized = SubscriptionAnalyticsSchema.model_validate(data).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription metrics fetched successfully.",
        data=serialized,
    )


def get_revenue_metrics(
    db: Session,
    user: UserModel,
    group_by: str = "daily",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Admin endpoint generating revenue breakdowns with daily, monthly, or yearly aggregation.
    """
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can access revenue reports.",
        )

    if group_by not in ["daily", "monthly", "yearly"]:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Invalid group_by parameter. Must be 'daily', 'monthly', or 'yearly'.",
        )

    s_date, e_date = _resolve_date_range(start_date, end_date)
    data = services.get_revenue_report(db, group_by, s_date, e_date)
    serialized = RevenueReportSchema.model_validate(data).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Revenue report generated successfully.",
        data=serialized,
    )


def get_churn_metrics(
    db: Session,
    user: UserModel,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Admin endpoint analyzing subscription cancellations, lost MRR, and churn rates.
    """
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can access churn analytics.",
        )

    s_date, e_date = _resolve_date_range(start_date, end_date)
    data = services.get_churn_analytics(db, s_date, e_date)
    serialized = ChurnAnalyticsSchema.model_validate(data).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Churn analytics calculated successfully.",
        data=serialized,
    )


def get_payment_metrics(
    db: Session,
    user: UserModel,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> ApiResponse:
    """
    Admin endpoint returning gateway attempts, success ratios, and refund metrics.
    """
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can access payment analytics.",
        )

    s_date, e_date = _resolve_date_range(start_date, end_date)
    data = services.get_payment_analytics(db, s_date, e_date)
    serialized = PaymentAnalyticsSchema.model_validate(data).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Payment analytics fetched successfully.",
        data=serialized,
    )

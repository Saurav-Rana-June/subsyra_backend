from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class CustomerHeroDto(BaseModel):
    """
    Subscriber hero banner schema for customer persona.
    """
    plan_name: str = Field(..., description="Active subscription plan name")
    status: str = Field(..., description="Subscription status (e.g. ACTIVE, TRIALING)")
    next_billing_date: Optional[datetime] = Field(None, description="Next renewal/billing timestamp")
    next_billing_amount: int = Field(..., description="Next billing amount in paise")
    currency: str = Field(default="INR", description="Three-letter currency code")
    payment_method: str = Field(default="Razorpay", description="Payment gateway or method label")


class KpiMetricDto(BaseModel):
    """
    Executive metric card schema for dashboard top row.
    """
    id: str = Field(..., description="Unique metric identifier (mrr, active_subs, churn_rate, overdue_invoices)")
    title: str = Field(..., description="Card display title")
    main_value: str = Field(..., description="Primary formatted KPI string (e.g. '₹ 50,000')")
    sub_value: Optional[str] = Field(None, description="Optional secondary context (e.g. ' / 1,500' or ' %')")
    badge_text: str = Field(..., description="Trend or status badge string (e.g. '↗ 12%')")
    badge_type: Literal["success", "danger", "info", "warning", "neutral"] = Field(
        default="success", description="Visual style category for the badge"
    )
    icon: str = Field(..., description="Lucide icon identifier (e.g. 'bar_chart', 'refresh_cw')")


class SubscriptionRowDto(BaseModel):
    """
    Single row schema for the Subscription Summary table.
    """
    id: int = Field(..., description="Subscription database ID")
    customer_name: str = Field(..., description="Full customer name or business name")
    customer_email: Optional[str] = Field(None, description="Customer contact email")
    plan_name: Optional[str] = Field(None, description="Subscribed plan name")
    renewal_date: Optional[datetime] = Field(None, description="Cycle renewal timestamp")
    status: str = Field(..., description="Status (ACTIVE, TRIALING, PAST_DUE, CANCELLED, EXPIRED)")
    price_amount: Optional[int] = Field(None, description="Price in paise")


class SubscriptionSummaryDto(BaseModel):
    """
    Subscription summary card data containing table rows and plan filter options.
    """
    plan_options: List[str] = Field(..., description="Filter options for plan dropdown")
    selected_plan: str = Field(default="Plan", description="Currently active plan filter")
    rows: List[SubscriptionRowDto] = Field(default_factory=list, description="Recent subscription records")


class StatusBarDto(BaseModel):
    """
    Single column bar item for subscription status distribution chart.
    """
    label: str = Field(..., description="Status label (Active, Trialing, Past Due, Cancelled)")
    count: int = Field(..., description="Absolute count of subscriptions in this status")
    percentage: str = Field(..., description="Formatted percentage label (e.g. '72%')")
    height_factor: float = Field(..., description="Normalized height factor between 0.0 and 1.0")


class SubscriptionStatusChartDto(BaseModel):
    """
    Subscription status distribution chart dataset.
    """
    status_options: List[str] = Field(..., description="Filter options for status dropdown")
    bars: List[StatusBarDto] = Field(default_factory=list, description="Status distribution bars")
    y_axis_labels: List[str] = Field(
        default=["100", "80", "60", "40", "20", "0"],
        description="Y-axis threshold markers"
    )


class DashboardDataDto(BaseModel):
    """
    Unified dashboard response payload supporting all roles (Admin & Customer).
    """
    role: str = Field(..., description="Active user role ('ADMIN' or 'CUSTOMER')")
    customer_hero: Optional[CustomerHeroDto] = Field(
        None, description="Hero card populated exclusively for CUSTOMER users"
    )
    selected_period: str = Field(default="Last 30 Days", description="Active date filter label")
    period_options: List[str] = Field(
        default=["Last 7 Days", "Last 30 Days", "Last 90 Days", "This Year", "All Time"],
        description="Available period filter dropdown options"
    )
    kpi_metrics: List[KpiMetricDto] = Field(
        default_factory=list, description="Top 4 KPI metric cards"
    )
    subscription_summary: SubscriptionSummaryDto = Field(
        ..., description="Subscription summary table and plan filter"
    )
    subscription_status_chart: SubscriptionStatusChartDto = Field(
        ..., description="Subscription status bar chart breakdown"
    )


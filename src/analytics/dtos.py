from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime


class OverviewMetricsSchema(BaseModel):
    """
    Executive KPI summary card schema.
    """
    mrr: int = Field(..., description="Monthly Recurring Revenue in paise")
    arr: int = Field(..., description="Annual Recurring Revenue in paise")
    active_subscriptions: int
    trialing_subscriptions: int
    gross_revenue_period: int = Field(..., description="Gross revenue in period (paise)")
    net_revenue_period: int = Field(..., description="Net revenue after refunds (paise)")
    total_refunded_period: int = Field(..., description="Total refunded in period (paise)")
    churn_rate_percent: float = Field(..., description="Subscription churn rate percentage")
    period_start: datetime
    period_end: datetime


class PlanDistributionItem(BaseModel):
    plan_id: int
    plan_name: str
    active_count: int


class SubscriptionAnalyticsSchema(BaseModel):
    """
    Subscription distribution by status and plan tiers.
    """
    total_subscriptions: int
    new_in_period: int
    by_status: Dict[str, int]
    by_plan: List[PlanDistributionItem]
    period_start: datetime
    period_end: datetime


class RevenueBreakdownItem(BaseModel):
    period_label: str  # e.g. "2026-10-24" or "2026-10" or "2026"
    gross_revenue: int
    refunded_amount: int
    net_revenue: int
    invoice_count: int


class RevenueReportSchema(BaseModel):
    """
    Historical revenue report grouped daily, monthly, or yearly.
    """
    group_by: Literal["daily", "monthly", "yearly"]
    total_gross_revenue: int
    total_refunded: int
    total_net_revenue: int
    currency: str
    breakdown: List[RevenueBreakdownItem]
    period_start: datetime
    period_end: datetime


class ChurnAnalyticsSchema(BaseModel):
    """
    Customer loss and cancellation metrics.
    """
    cancellations_count: int
    expirations_count: int
    total_churned: int
    active_baseline: int
    churn_rate_percent: float
    lost_mrr: int = Field(..., description="Lost monthly recurring revenue in paise")
    period_start: datetime
    period_end: datetime


class PaymentAnalyticsSchema(BaseModel):
    """
    Payment gateway attempts, success rate, and refund volumes.
    """
    total_attempts: int
    successful_count: int
    failed_count: int
    refunded_count: int
    partially_refunded_count: int
    success_rate_percent: float
    total_successful_volume: int = Field(..., description="Successful volume in paise")
    total_refunded_volume: int = Field(..., description="Refunded volume in paise")
    period_start: datetime
    period_end: datetime

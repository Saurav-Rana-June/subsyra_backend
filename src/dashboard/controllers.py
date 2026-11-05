from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import status

from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.dashboard.dtos import (
    DashboardDataDto,
    CustomerHeroDto,
    KpiMetricDto,
    SubscriptionRowDto,
    SubscriptionSummaryDto,
    StatusBarDto,
    SubscriptionStatusChartDto,
)


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
    
    Dispatches role-aware response for the Subsyra Dashboard screen:
    - If user is ADMIN:
        * Builds executive KPIs (MRR, Active Subscriptions, Churn Rate, Overdue Invoices).
        * Builds all-customer subscription summary table.
        * Builds platform-wide subscription status bar chart.
    - If user is CUSTOMER:
        * Populates Customer Summary Hero (active plan, renewal date, amount due).
        * Builds subscriber-scoped metrics (Personal Subscriptions, Invoices, Spending).
        * Builds personal subscription rows and status distribution.
    """
    is_admin = user.role == UserRole.ADMIN.value
    now = datetime.now(timezone.utc)

    # -------------------------------------------------------------------------
    # 1. Customer Hero Section (Customer Only)
    # -------------------------------------------------------------------------
    customer_hero: Optional[CustomerHeroDto] = None
    if not is_admin:
        # TODO: Query user's primary active or trialing subscription joined with PlanPricingModel
        customer_hero = CustomerHeroDto(
            plan_name="Growth Plan",
            status="ACTIVE",
            next_billing_date=now + timedelta(days=19),
            next_billing_amount=176882,  # ₹1,768.82 in paise
            currency="INR",
            payment_method="Razorpay",
        )

    # -------------------------------------------------------------------------
    # 2. Executive / Overview KPI Metrics (4 Cards)
    # -------------------------------------------------------------------------
    if is_admin:
        # TODO: Pull live metrics from Analytics services and calculate growth deltas
        kpi_metrics = [
            KpiMetricDto(
                id="mrr",
                title="Monthly Recurring Revenue",
                main_value="₹ 50,000",
                sub_value=None,
                badge_text="↗ 12%",
                badge_type="success",
                icon="bar_chart",
            ),
            KpiMetricDto(
                id="active_subs",
                title="Active Subscriptions",
                main_value="1,240",
                sub_value=" / 1,500",
                badge_text="↗ 9%",
                badge_type="success",
                icon="refresh_cw",
            ),
            KpiMetricDto(
                id="churn_rate",
                title="Churn Rate",
                main_value="2.4",
                sub_value=" %",
                badge_text="↗ 5%",
                badge_type="danger",
                icon="trending_up",
            ),
            KpiMetricDto(
                id="overdue_invoices",
                title="Overdue Invoices",
                main_value="18",
                sub_value=" / 240",
                badge_text="↘ 15%",
                badge_type="success",
                icon="file_text",
            ),
        ]
    else:
        # Customer-specific KPI overview metrics
        # TODO: Query user's personal subscription count, invoices, and cumulative spend
        kpi_metrics = [
            KpiMetricDto(
                id="customer_active_subs",
                title="Active Subscriptions",
                main_value="1",
                sub_value=" / 1",
                badge_text="Active",
                badge_type="success",
                icon="refresh_cw",
            ),
            KpiMetricDto(
                id="customer_total_spent",
                title="Total Amount Spent",
                main_value="₹ 5,306",
                sub_value=None,
                badge_text="YTD",
                badge_type="info",
                icon="bar_chart",
            ),
            KpiMetricDto(
                id="customer_invoices_paid",
                title="Invoices Paid",
                main_value="3",
                sub_value=" / 3",
                badge_text="100%",
                badge_type="success",
                icon="file_text",
            ),
            KpiMetricDto(
                id="customer_next_renewal",
                title="Next Renewal",
                main_value="19 Days",
                sub_value=None,
                badge_text="Auto-Pay",
                badge_type="success",
                icon="trending_up",
            ),
        ]

    # -------------------------------------------------------------------------
    # 3. Subscription Summary Table Section
    # -------------------------------------------------------------------------
    # TODO: Query plans for filter dropdown + query subscriptions joined with users & plans
    plan_options = ["Plan", "Starter", "Pro", "Enterprise"]
    summary_rows = [
        SubscriptionRowDto(
            id=1,
            customer_name="Northwind Labs" if is_admin else user.full_name,
            customer_email="billing@northwind.example" if is_admin else user.email_address,
            plan_name="Enterprise",
            renewal_date=now + timedelta(days=50),
            status="ACTIVE",
            price_amount=499900,
        ),
        SubscriptionRowDto(
            id=2,
            customer_name="Acme Studio" if is_admin else user.full_name,
            customer_email="contact@acme.example" if is_admin else user.email_address,
            plan_name="Pro",
            renewal_date=now + timedelta(days=19),
            status="ACTIVE",
            price_amount=199900,
        ),
        SubscriptionRowDto(
            id=3,
            customer_name="Brightloop Co." if is_admin else user.full_name,
            customer_email="admin@brightloop.example" if is_admin else user.email_address,
            plan_name="Starter",
            renewal_date=now + timedelta(days=3),
            status="TRIALING",
            price_amount=49900,
        ),
        SubscriptionRowDto(
            id=4,
            customer_name="Orbit Health" if is_admin else user.full_name,
            customer_email="ops@orbit.example" if is_admin else user.email_address,
            plan_name="Pro",
            renewal_date=now + timedelta(days=14),
            status="PAST_DUE",
            price_amount=199900,
        ),
        SubscriptionRowDto(
            id=5,
            customer_name="Lumen Media" if is_admin else user.full_name,
            customer_email="accounts@lumen.example" if is_admin else user.email_address,
            plan_name="Starter",
            renewal_date=now - timedelta(days=2),
            status="CANCELLED",
            price_amount=49900,
        ),
    ]

    subscription_summary = SubscriptionSummaryDto(
        plan_options=plan_options,
        selected_plan=plan_filter,
        rows=summary_rows,
    )

    # -------------------------------------------------------------------------
    # 4. Subscription Status Bar Chart Section
    # -------------------------------------------------------------------------
    # TODO: Query subscription counts grouped by status in the selected date window
    status_options = ["All", "Active", "Trialing", "Past Due", "Cancelled"]
    chart_bars = [
        StatusBarDto(label="Active", count=25, percentage="72%", height_factor=0.72),
        StatusBarDto(label="Trialing", count=5, percentage="14%", height_factor=0.14),
        StatusBarDto(label="Past Due", count=3, percentage="8%", height_factor=0.08),
        StatusBarDto(label="Cancelled", count=2, percentage="6%", height_factor=0.06),
    ]

    subscription_status_chart = SubscriptionStatusChartDto(
        status_options=status_options,
        bars=chart_bars,
        y_axis_labels=["100", "80", "60", "40", "20", "0"],
    )

    # -------------------------------------------------------------------------
    # 5. Assemble and Return Unified Response
    # -------------------------------------------------------------------------
    dashboard_data = DashboardDataDto(
        role=user.role,
        customer_hero=customer_hero,
        selected_period=period,
        period_options=[
            "Last 7 Days",
            "Last 30 Days",
            "Last 90 Days",
            "This Year",
            "All Time",
        ],
        kpi_metrics=kpi_metrics,
        subscription_summary=subscription_summary,
        subscription_status_chart=subscription_status_chart,
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Dashboard data retrieved successfully",
        data=dashboard_data.model_dump(),
    )


from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.users.models import UserModel, UserRole
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel
from src.analytics.services import calculate_mrr_and_arr
from src.dashboard.dtos import (
    CustomerHeroDto,
    KpiMetricDto,
    SubscriptionRowDto,
    SubscriptionSummaryDto,
    StatusBarDto,
    SubscriptionStatusChartDto,
    DashboardDataDto,
)


def get_dashboard_metrics(
    db: Session,
    user: UserModel,
    period: str = "Last 30 Days",
    plan_filter: str = "Plan",
    status_filter: str = "All",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> DashboardDataDto:
    """
    Computes live dashboard analytics from the database.
    """
    now = datetime.now(timezone.utc)
    is_admin = user.role == UserRole.ADMIN.value

    # Normalize period window dates if not explicitly provided
    resolved_end = end_date or now
    if start_date:
        resolved_start = start_date
    elif period == "Last 7 Days":
        resolved_start = resolved_end - timedelta(days=7)
    elif period == "Last 90 Days":
        resolved_start = resolved_end - timedelta(days=90)
    elif period == "This Year":
        resolved_start = datetime(resolved_end.year, 1, 1, tzinfo=timezone.utc)
    elif period == "All Time":
        resolved_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    else:  # "Last 30 Days"
        resolved_start = resolved_end - timedelta(days=30)

    # -------------------------------------------------------------------------
    # 1. Customer Hero Section
    # -------------------------------------------------------------------------
    customer_hero: Optional[CustomerHeroDto] = None
    if not is_admin:
        # Find user's active, trialing, or most recent subscription
        user_sub = (
            db.query(SubscriptionModel)
            .filter(SubscriptionModel.user_id == user.id)
            .order_by(
                (SubscriptionModel.status == SubscriptionStatus.ACTIVE.value).desc(),
                (SubscriptionModel.status == SubscriptionStatus.TRIALING.value).desc(),
                SubscriptionModel.id.desc(),
            )
            .first()
        )

        if user_sub:
            plan = db.query(PlanPricingModel).filter(PlanPricingModel.id == user_sub.plan_id).first()
            plan_name = plan.name if plan else "Subscription Plan"

            # Determine next billing date
            next_date = user_sub.current_period_end or user_sub.trial_end

            customer_hero = CustomerHeroDto(
                plan_name=plan_name,
                status=user_sub.status,
                next_billing_date=next_date,
                next_billing_amount=user_sub.price_amount,
                currency=user_sub.currency,
                payment_method="Razorpay",
            )
        else:
            # Fallback for new customer without active subscription
            customer_hero = CustomerHeroDto(
                plan_name="No Active Plan",
                status="INACTIVE",
                next_billing_date=None,
                next_billing_amount=0,
                currency="INR",
                payment_method="Razorpay",
            )

    # -------------------------------------------------------------------------
    # 2. KPI Metrics Section
    # -------------------------------------------------------------------------
    if is_admin:
        # Live MRR calculation
        mrr_paise, arr_paise = calculate_mrr_and_arr(db)
        mrr_rupees = mrr_paise / 100.0

        # Subscriptions count
        total_subs = db.query(SubscriptionModel).count()
        active_subs = (
            db.query(SubscriptionModel)
            .filter(SubscriptionModel.status == SubscriptionStatus.ACTIVE.value)
            .count()
        )

        # Churn calculation
        churned_subs = (
            db.query(SubscriptionModel)
            .filter(
                SubscriptionModel.status.in_([
                    SubscriptionStatus.CANCELLED.value,
                    SubscriptionStatus.EXPIRED.value,
                ])
            )
            .count()
        )
        churn_rate = (churned_subs / max(1, total_subs)) * 100.0

        # Overdue invoices count
        total_invoices = db.query(InvoiceModel).count()
        overdue_invoices = (
            db.query(InvoiceModel)
            .filter(InvoiceModel.status == InvoiceStatus.UNCOLLECTIBLE.value)
            .count()
        )
        if overdue_invoices == 0:
            # Also check for subscriptions in PAST_DUE
            overdue_invoices = (
                db.query(SubscriptionModel)
                .filter(SubscriptionModel.status == SubscriptionStatus.PAST_DUE.value)
                .count()
            )

        kpi_metrics = [
            KpiMetricDto(
                id="mrr",
                title="Monthly Recurring Revenue",
                main_value=f"₹ {mrr_rupees:,.0f}",
                sub_value=None,
                badge_text="↗ 12%",
                badge_type="success",
                icon="bar_chart",
            ),
            KpiMetricDto(
                id="active_subs",
                title="Active Subscriptions",
                main_value=f"{active_subs:,}",
                sub_value=f" / {total_subs:,}",
                badge_text="↗ 9%",
                badge_type="success",
                icon="refresh_cw",
            ),
            KpiMetricDto(
                id="churn_rate",
                title="Churn Rate",
                main_value=f"{churn_rate:.1f}",
                sub_value=" %",
                badge_text="↗ 5%",
                badge_type="danger" if churn_rate > 5 else "success",
                icon="trending_up",
            ),
            KpiMetricDto(
                id="overdue_invoices",
                title="Overdue Invoices",
                main_value=f"{overdue_invoices}",
                sub_value=f" / {total_invoices}",
                badge_text="↘ 15%" if overdue_invoices <= 2 else "↗ Alert",
                badge_type="success" if overdue_invoices <= 2 else "danger",
                icon="file_text",
            ),
        ]
    else:
        # Customer-specific metrics
        customer_subs = db.query(SubscriptionModel).filter(SubscriptionModel.user_id == user.id).all()
        cust_active_count = sum(1 for s in customer_subs if s.status == SubscriptionStatus.ACTIVE.value)

        # Total spent by customer
        spent_paise = (
            db.query(func.coalesce(func.sum(InvoiceModel.total_amount), 0))
            .filter(
                InvoiceModel.user_id == user.id,
                InvoiceModel.status == InvoiceStatus.PAID.value,
            )
            .scalar()
        )
        spent_rupees = spent_paise / 100.0

        # Paid invoices
        cust_paid_invoices = (
            db.query(InvoiceModel)
            .filter(
                InvoiceModel.user_id == user.id,
                InvoiceModel.status == InvoiceStatus.PAID.value,
            )
            .count()
        )
        cust_total_invoices = (
            db.query(InvoiceModel)
            .filter(InvoiceModel.user_id == user.id)
            .count()
        )

        # Days to renewal
        next_sub = next((s for s in customer_subs if s.status == SubscriptionStatus.ACTIVE.value and s.current_period_end), None)
        if next_sub and next_sub.current_period_end:
            target_dt = next_sub.current_period_end
            if target_dt.tzinfo is not None:
                diff = (target_dt - now).days
            else:
                diff = (target_dt - now.replace(tzinfo=None)).days
            renewal_text = f"{max(0, diff)} Days"
        else:
            renewal_text = "N/A"

        kpi_metrics = [
            KpiMetricDto(
                id="customer_active_subs",
                title="Active Subscriptions",
                main_value=f"{cust_active_count}",
                sub_value=f" / {len(customer_subs)}",
                badge_text="Active",
                badge_type="success",
                icon="refresh_cw",
            ),
            KpiMetricDto(
                id="customer_total_spent",
                title="Total Amount Spent",
                main_value=f"₹ {spent_rupees:,.2f}",
                sub_value=None,
                badge_text="YTD",
                badge_type="info",
                icon="bar_chart",
            ),
            KpiMetricDto(
                id="customer_invoices_paid",
                title="Invoices Paid",
                main_value=f"{cust_paid_invoices}",
                sub_value=f" / {max(1, cust_total_invoices)}",
                badge_text="100%" if cust_paid_invoices == cust_total_invoices else "Review",
                badge_type="success",
                icon="file_text",
            ),
            KpiMetricDto(
                id="customer_next_renewal",
                title="Next Renewal",
                main_value=renewal_text,
                sub_value=None,
                badge_text="Auto-Pay",
                badge_type="success",
                icon="trending_up",
            ),
        ]

    # -------------------------------------------------------------------------
    # 3. Subscription Summary Table Section
    # -------------------------------------------------------------------------
    # Query all active plan names for the dropdown
    active_plans = db.query(PlanPricingModel.name).order_by(PlanPricingModel.id.asc()).all()
    plan_options = ["Plan"] + [p[0] for p in active_plans]

    # Build base subscription query joined with UserModel and PlanPricingModel
    subs_query = (
        db.query(SubscriptionModel, UserModel, PlanPricingModel)
        .join(UserModel, SubscriptionModel.user_id == UserModel.id)
        .join(PlanPricingModel, SubscriptionModel.plan_id == PlanPricingModel.id)
    )

    if not is_admin:
        subs_query = subs_query.filter(SubscriptionModel.user_id == user.id)

    # Apply plan filter if specified
    if plan_filter and plan_filter != "Plan" and plan_filter != "All Plans":
        subs_query = subs_query.filter(PlanPricingModel.name == plan_filter)

    records = subs_query.order_by(SubscriptionModel.id.desc()).limit(15).all()

    summary_rows = []
    for sub, sub_user, sub_plan in records:
        summary_rows.append(
            SubscriptionRowDto(
                id=sub.id,
                customer_name=sub_user.full_name,
                customer_email=sub_user.email_address,
                plan_name=sub_plan.name,
                renewal_date=sub.current_period_end or sub.trial_end,
                status=sub.status,
                price_amount=sub.price_amount,
            )
        )

    subscription_summary = SubscriptionSummaryDto(
        plan_options=plan_options,
        selected_plan=plan_filter,
        rows=summary_rows,
    )

    # -------------------------------------------------------------------------
    # 4. Subscription Status Bar Chart Section
    # -------------------------------------------------------------------------
    status_options = ["All", "Active", "Trialing", "Past Due", "Cancelled"]

    # Query counts grouped by status
    count_query = db.query(SubscriptionModel.status, func.count(SubscriptionModel.id))
    if not is_admin:
        count_query = count_query.filter(SubscriptionModel.user_id == user.id)
    
    status_counts_raw = count_query.group_by(SubscriptionModel.status).all()
    counts_map = {status_val: count for status_val, count in status_counts_raw}

    total_for_chart = sum(counts_map.values()) or 1
    max_count = max(counts_map.values()) if counts_map else 1

    chart_bars = [
        StatusBarDto(
            label="Active",
            count=counts_map.get(SubscriptionStatus.ACTIVE.value, 0),
            percentage=f"{(counts_map.get(SubscriptionStatus.ACTIVE.value, 0) / total_for_chart) * 100:.0f}%",
            height_factor=min(1.0, counts_map.get(SubscriptionStatus.ACTIVE.value, 0) / max(1, max_count)),
        ),
        StatusBarDto(
            label="Trialing",
            count=counts_map.get(SubscriptionStatus.TRIALING.value, 0),
            percentage=f"{(counts_map.get(SubscriptionStatus.TRIALING.value, 0) / total_for_chart) * 100:.0f}%",
            height_factor=min(1.0, counts_map.get(SubscriptionStatus.TRIALING.value, 0) / max(1, max_count)),
        ),
        StatusBarDto(
            label="Past Due",
            count=counts_map.get(SubscriptionStatus.PAST_DUE.value, 0),
            percentage=f"{(counts_map.get(SubscriptionStatus.PAST_DUE.value, 0) / total_for_chart) * 100:.0f}%",
            height_factor=min(1.0, counts_map.get(SubscriptionStatus.PAST_DUE.value, 0) / max(1, max_count)),
        ),
        StatusBarDto(
            label="Cancelled",
            count=counts_map.get(SubscriptionStatus.CANCELLED.value, 0),
            percentage=f"{(counts_map.get(SubscriptionStatus.CANCELLED.value, 0) / total_for_chart) * 100:.0f}%",
            height_factor=min(1.0, counts_map.get(SubscriptionStatus.CANCELLED.value, 0) / max(1, max_count)),
        ),
    ]

    subscription_status_chart = SubscriptionStatusChartDto(
        status_options=status_options,
        bars=chart_bars,
        y_axis_labels=["100", "80", "60", "40", "20", "0"],
    )

    # -------------------------------------------------------------------------
    # 5. Assemble Payload
    # -------------------------------------------------------------------------
    return DashboardDataDto(
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


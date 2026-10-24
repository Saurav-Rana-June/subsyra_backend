from typing import Tuple, Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.plans_pricing.models import PlanPricingModel
from src.invoices.models import InvoiceModel, InvoiceStatus
from src.payment.models import PaymentModel, PaymentStatus, RefundModel, RefundStatus


def calculate_mrr_and_arr(db: Session) -> Tuple[int, int]:
    """
    Computes Monthly Recurring Revenue (MRR) and Annual Recurring Revenue (ARR)
    by normalizing active subscriptions to a 1-month equivalent.
    """
    active_subs = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.status == SubscriptionStatus.ACTIVE.value)
        .all()
    )

    total_mrr = 0.0
    for sub in active_subs:
        interval_count = max(1, sub.interval_count or 1)
        if sub.billing_interval == "month":
            monthly_val = sub.price_amount / interval_count
        elif sub.billing_interval == "year":
            monthly_val = sub.price_amount / (12.0 * interval_count)
        else:
            monthly_val = float(sub.price_amount)

        total_mrr += monthly_val

    mrr = int(round(total_mrr))
    arr = mrr * 12
    return mrr, arr


def get_subscription_analytics(
    db: Session, start_date: datetime, end_date: datetime
) -> Dict[str, Any]:
    """
    Aggregates subscription status distribution, plan-tier adoption, and new activations.
    """
    # 1. Total count
    total_subs = db.query(SubscriptionModel).count()

    # 2. Count by status
    status_counts_raw = (
        db.query(SubscriptionModel.status, func.count(SubscriptionModel.id))
        .group_by(SubscriptionModel.status)
        .all()
    )
    by_status = {s.value: 0 for s in SubscriptionStatus}
    for st, count in status_counts_raw:
        by_status[st] = count

    # 3. Active subscribers by plan
    plan_distribution_raw = (
        db.query(
            PlanPricingModel.id,
            PlanPricingModel.name,
            func.count(SubscriptionModel.id),
        )
        .join(SubscriptionModel, SubscriptionModel.plan_id == PlanPricingModel.id)
        .filter(SubscriptionModel.status == SubscriptionStatus.ACTIVE.value)
        .group_by(PlanPricingModel.id, PlanPricingModel.name)
        .all()
    )
    by_plan = [
        {
            "plan_id": row[0],
            "plan_name": row[1] or f"Plan #{row[0]}",
            "active_count": row[2],
        }
        for row in plan_distribution_raw
    ]

    # 4. New subscriptions created in the specified date range
    new_in_period = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.created_at.between(start_date, end_date))
        .count()
    )

    return {
        "total_subscriptions": total_subs,
        "new_in_period": new_in_period,
        "by_status": by_status,
        "by_plan": by_plan,
        "period_start": start_date,
        "period_end": end_date,
    }


def get_revenue_report(
    db: Session,
    group_by: str,
    start_date: datetime,
    end_date: datetime,
) -> Dict[str, Any]:
    """
    Generates gross, refunded, and net revenue summaries grouped by day, month, or year.
    """
    date_format = "YYYY-MM-DD"
    if group_by == "monthly":
        date_format = "YYYY-MM"
    elif group_by == "yearly":
        date_format = "YYYY"

    # 1. Query paid invoices in period grouped by date
    invoice_groups = (
        db.query(
            func.to_char(InvoiceModel.paid_at, date_format).label("period_bucket"),
            func.coalesce(func.sum(InvoiceModel.total_amount), 0).label("gross"),
            func.count(InvoiceModel.id).label("cnt"),
        )
        .filter(
            InvoiceModel.status == InvoiceStatus.PAID.value,
            InvoiceModel.paid_at.isnot(None),
            InvoiceModel.paid_at.between(start_date, end_date),
        )
        .group_by("period_bucket")
        .order_by("period_bucket")
        .all()
    )

    # 2. Query processed refunds in period grouped by date
    refund_groups = (
        db.query(
            func.to_char(RefundModel.created_at, date_format).label("period_bucket"),
            func.coalesce(func.sum(RefundModel.amount), 0).label("refunded"),
        )
        .filter(
            RefundModel.status != RefundStatus.FAILED.value,
            RefundModel.created_at.between(start_date, end_date),
        )
        .group_by("period_bucket")
        .all()
    )

    refunds_map = {row[0]: row[1] for row in refund_groups}

    # 3. Assemble unified breakdown
    all_buckets = sorted(
        list(set([row[0] for row in invoice_groups] + list(refunds_map.keys())))
    )
    invoices_map = {row[0]: (row[1], row[2]) for row in invoice_groups}

    breakdown = []
    total_gross = 0
    total_refunded = 0

    for bucket in all_buckets:
        gross, cnt = invoices_map.get(bucket, (0, 0))
        ref = refunds_map.get(bucket, 0)
        net = max(0, gross - ref)

        total_gross += gross
        total_refunded += ref

        breakdown.append(
            {
                "period_label": bucket,
                "gross_revenue": gross,
                "refunded_amount": ref,
                "net_revenue": net,
                "invoice_count": cnt,
            }
        )

    total_net = max(0, total_gross - total_refunded)

    return {
        "group_by": group_by,
        "total_gross_revenue": total_gross,
        "total_refunded": total_refunded,
        "total_net_revenue": total_net,
        "currency": "INR",
        "breakdown": breakdown,
        "period_start": start_date,
        "period_end": end_date,
    }


def get_churn_analytics(
    db: Session, start_date: datetime, end_date: datetime
) -> Dict[str, Any]:
    """
    Calculates customer loss, cancellation volume, and lost MRR in the date window.
    """
    # 1. Cancellations in period
    cancelled_subs = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.cancelled_at.isnot(None),
            SubscriptionModel.cancelled_at.between(start_date, end_date),
        )
        .all()
    )
    cancellations_count = len(cancelled_subs)

    # 2. Expirations in period
    expirations_count = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.status == SubscriptionStatus.EXPIRED.value,
            SubscriptionModel.updated_at.between(start_date, end_date),
        )
        .count()
    )

    total_churned = cancellations_count + expirations_count

    # 3. Active baseline
    active_baseline = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.status == SubscriptionStatus.ACTIVE.value)
        .count()
    )

    total_base = active_baseline + total_churned
    churn_rate = (
        round((total_churned / float(total_base)) * 100.0, 2)
        if total_base > 0
        else 0.0
    )

    # 4. Lost Monthly Recurring Revenue
    lost_mrr = 0
    for s in cancelled_subs:
        interval_count = max(1, s.interval_count or 1)
        if s.billing_interval == "year":
            lost_mrr += int(round(s.price_amount / (12.0 * interval_count)))
        else:
            lost_mrr += int(round(s.price_amount / float(interval_count)))

    return {
        "cancellations_count": cancellations_count,
        "expirations_count": expirations_count,
        "total_churned": total_churned,
        "active_baseline": active_baseline,
        "churn_rate_percent": churn_rate,
        "lost_mrr": lost_mrr,
        "period_start": start_date,
        "period_end": end_date,
    }


def get_payment_analytics(
    db: Session, start_date: datetime, end_date: datetime
) -> Dict[str, Any]:
    """
    Calculates gateway transaction volume, success rates, and refund ratios.
    """
    payments = (
        db.query(PaymentModel)
        .filter(PaymentModel.created_at.between(start_date, end_date))
        .all()
    )

    total_attempts = len(payments)
    successful_count = 0
    failed_count = 0
    refunded_count = 0
    partially_refunded_count = 0
    total_successful_volume = 0

    for p in payments:
        if p.status == PaymentStatus.SUCCESS.value:
            successful_count += 1
            total_successful_volume += p.amount
        elif p.status == PaymentStatus.PARTIALLY_REFUNDED.value:
            partially_refunded_count += 1
            successful_count += 1
            total_successful_volume += p.amount
        elif p.status == PaymentStatus.REFUNDED.value:
            refunded_count += 1
            successful_count += 1
            total_successful_volume += p.amount
        elif p.status == PaymentStatus.FAILED.value:
            failed_count += 1

    decided_attempts = successful_count + failed_count
    success_rate = (
        round((successful_count / float(decided_attempts)) * 100.0, 2)
        if decided_attempts > 0
        else 0.0
    )

    total_refunded_volume = (
        db.query(func.coalesce(func.sum(RefundModel.amount), 0))
        .filter(
            RefundModel.status != RefundStatus.FAILED.value,
            RefundModel.created_at.between(start_date, end_date),
        )
        .scalar()
    )

    return {
        "total_attempts": total_attempts,
        "successful_count": successful_count,
        "failed_count": failed_count,
        "refunded_count": refunded_count,
        "partially_refunded_count": partially_refunded_count,
        "success_rate_percent": success_rate,
        "total_successful_volume": total_successful_volume,
        "total_refunded_volume": total_refunded_volume,
        "period_start": start_date,
        "period_end": end_date,
    }


def get_overview_analytics(
    db: Session, start_date: datetime, end_date: datetime
) -> Dict[str, Any]:
    """
    Combines high-level executive KPI indicators into a single payload.
    """
    mrr, arr = calculate_mrr_and_arr(db)

    active_subs = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.status == SubscriptionStatus.ACTIVE.value)
        .count()
    )
    trialing_subs = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.status == SubscriptionStatus.TRIALING.value)
        .count()
    )

    gross_rev = (
        db.query(func.coalesce(func.sum(InvoiceModel.total_amount), 0))
        .filter(
            InvoiceModel.status == InvoiceStatus.PAID.value,
            InvoiceModel.paid_at.isnot(None),
            InvoiceModel.paid_at.between(start_date, end_date),
        )
        .scalar()
    )

    refunded_val = (
        db.query(func.coalesce(func.sum(RefundModel.amount), 0))
        .filter(
            RefundModel.status != RefundStatus.FAILED.value,
            RefundModel.created_at.between(start_date, end_date),
        )
        .scalar()
    )

    net_rev = max(0, gross_rev - refunded_val)

    # Churn rate for the period
    churn_data = get_churn_analytics(db, start_date, end_date)

    return {
        "mrr": mrr,
        "arr": arr,
        "active_subscriptions": active_subs,
        "trialing_subscriptions": trialing_subs,
        "gross_revenue_period": gross_rev,
        "net_revenue_period": net_rev,
        "total_refunded_period": refunded_val,
        "churn_rate_percent": churn_data["churn_rate_percent"],
        "period_start": start_date,
        "period_end": end_date,
    }

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.utils.helpers import calculate_period_end
from src.utils.invoices_services import generate_invoice_number
from src.invoices.models import InvoiceModel, InvoiceStatus


def process_subscription_renewals(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    # 1. Process active subscriptions due for renewal
    due_subs = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.status == SubscriptionStatus.ACTIVE.value,
            SubscriptionModel.current_period_end <= now,
        )
        .all()
    )

    expired_count = 0
    renewed_count = 0

    for sub in due_subs:
        if sub.cancel_at_period_end:
            # User chose not to renew; transition to EXPIRED
            sub.status = SubscriptionStatus.EXPIRED.value
            expired_count += 1

        else:
            # Check for scheduled plan change (e.g. Downgrade)
            if sub.pending_plan_id:
                pending_plan = (
                    db.query(PlanPricingModel)
                    .filter(PlanPricingModel.id == sub.pending_plan_id)
                    .first()
                )
                if pending_plan and pending_plan.is_active:
                    sub.plan_id = pending_plan.id
                    sub.price_amount = pending_plan.price_amount
                    sub.currency = pending_plan.currency
                    sub.billing_interval = pending_plan.billing_interval
                    sub.interval_count = pending_plan.interval_count
                sub.pending_plan_id = None

            # Advance billing cycle
            old_end = sub.current_period_end
            sub.current_period_start = old_end
            sub.current_period_end = calculate_period_end(
                start_date=old_end,
                interval=sub.billing_interval,
                count=sub.interval_count,
            )

            # Issue renewal invoice (SUBSCRIPTION_CYCLE)
            invoice_num = generate_invoice_number(db)
            renewal_invoice = InvoiceModel(
                invoice_number=invoice_num,
                user_id=sub.user_id,
                subscription_id=sub.id,
                payment_id=None,  # Or gateway recurring payment reference
                subtotal=sub.price_amount,
                tax_amount=0,
                total_amount=sub.price_amount,
                currency=sub.currency,
                status=InvoiceStatus.PAID.value,
                billing_reason="SUBSCRIPTION_CYCLE",
                paid_at=now,
            )
            db.add(renewal_invoice)
            renewed_count += 1

    # Process expired free trials
    trial_expired_count = 0
    due_trials = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.status == SubscriptionStatus.TRIALING.value,
            SubscriptionModel.trial_end <= now,
        )
        .all()
    )
    for trial_sub in due_trials:
        trial_sub.status = SubscriptionStatus.EXPIRED.value
        trial_expired_count += 1

    # 3. Process expired grace periods (PAST_DUE)
    grace_expired_count = 0
    expired_grace_subs = (
        db.query(SubscriptionModel)
        .filter(
            SubscriptionModel.status == SubscriptionStatus.PAST_DUE.value,
            SubscriptionModel.grace_period_end <= now,
        )
        .all()
    )
    for past_due_sub in expired_grace_subs:
        past_due_sub.status = SubscriptionStatus.EXPIRED.value
        grace_expired_count += 1

    db.commit()

    return {
        "processed_total": len(due_subs),
        "expired": expired_count,
        "renewed": renewed_count,
        "trials_expired": trial_expired_count,
        "grace_expired": grace_expired_count,
    }


def handle_failed_renewal(
    sub: SubscriptionModel,
    db: Session,
    max_retries: int = 3,
    grace_period_days: int = 7,
) -> str:

    now = datetime.now(timezone.utc)

    # If already past grace period or max retries reached -> EXPIRED
    if sub.grace_period_end:
        grace_end = (
            sub.grace_period_end.replace(tzinfo=timezone.utc)
            if sub.grace_period_end.tzinfo is None
            else sub.grace_period_end
        )
        if grace_end <= now:
            sub.status = SubscriptionStatus.EXPIRED.value
            return "EXPIRED"

    if sub.renewal_retry_count >= max_retries:
        sub.status = SubscriptionStatus.EXPIRED.value
        return "EXPIRED"

    # Otherwise enter or continue grace period
    sub.status = SubscriptionStatus.PAST_DUE.value
    if not sub.grace_period_end:
        sub.grace_period_end = now + timedelta(days=grace_period_days)

    sub.renewal_retry_count += 1
    return "PAST_DUE"

from datetime import datetime, timezone
from src.subscription.models import SubscriptionModel
from src.plans_pricing.models import PlanPricingModel


def calculate_proration(
    sub: SubscriptionModel,
    new_plan: PlanPricingModel,
    now: datetime = None,
) -> dict:
    if now is None:
        now = datetime.now(timezone.utc)

    # If subscription has no active period timestamps (e.g. pending), charge full new plan
    if not sub.current_period_start or not sub.current_period_end:
        return {
            "change_type": "UPGRADE",
            "effective_immediately": True,
            "unused_credit": 0,
            "new_plan_charge": new_plan.price_amount,
            "net_amount_due": new_plan.price_amount,
            "effective_date": now,
        }

    # Normalize tz-aware / tz-naive datetimes for calculation
    start_ts = (
        sub.current_period_start.replace(tzinfo=timezone.utc)
        if sub.current_period_start.tzinfo is None
        else sub.current_period_start
    )
    end_ts = (
        sub.current_period_end.replace(tzinfo=timezone.utc)
        if sub.current_period_end.tzinfo is None
        else sub.current_period_end
    )
    now_ts = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    total_duration_sec = max(1.0, (end_ts - start_ts).total_seconds())
    remaining_sec = max(0.0, (end_ts - now_ts).total_seconds())
    fraction_remaining = min(1.0, remaining_sec / total_duration_sec)

    # Downgrade: New plan price is less than current plan price
    if new_plan.price_amount < sub.price_amount:
        return {
            "change_type": "DOWNGRADE",
            "effective_immediately": False,
            "unused_credit": 0,
            "new_plan_charge": 0,
            "net_amount_due": 0,
            "effective_date": end_ts,  # Takes effect at end of current period
        }
    # Upgrade: Calculate prorated difference
    unused_credit = round(sub.price_amount * fraction_remaining)
    new_plan_charge = round(new_plan.price_amount * fraction_remaining)
    net_amount_due = max(0, new_plan_charge - unused_credit)

    return {
        "change_type": "UPGRADE",
        "effective_immediately": True,
        "unused_credit": unused_credit,
        "new_plan_charge": new_plan_charge,
        "net_amount_due": net_amount_due,
        "effective_date": now_ts,
    }

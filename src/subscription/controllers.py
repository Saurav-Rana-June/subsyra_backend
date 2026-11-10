from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from fastapi import status
from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.subscription.models import SubscriptionModel, SubscriptionPaymentMethodModel
from src.plans_pricing.models import PlanPricingModel
from src.utils.proration import calculate_proration
from src.subscription.dtos import (
    SubscriptionStatus,
    SubscriptionCreateSchema,
    SubscriptionReadSchema,
    PlanChangeRequestSchema,
    PaymentMethodUpdateSchema,
    PaymentMethodReadSchema,
    SubscriptionActivityItemSchema,
    SubscriptionDetailsReadSchema,
)
from src.utils.payment_services import create_razorpay_order
from src.payment.models import PaymentModel, PaymentStatus
from src.payment.dtos import PaymentReadSchema
from src.invoices.models import InvoiceModel
from src.invoices.dtos import InvoiceReadSchema
from src.audit_logs.models import AuditLogModel
from src.utils.settings import settings
from src.audit_logs.services import record_audit_log
from src.utils.redis_cache import redis_cache


def create_subscription(body: SubscriptionCreateSchema, db: Session, user: UserModel):
    plan = (
        db.query(PlanPricingModel).filter(PlanPricingModel.id == body.plan_id).first()
    )

    if not plan:
        return ApiResponse(status=status.HTTP_404_NOT_FOUND, message="Plan not found")

    if not plan.is_active:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="this plan is archived or inactive and cannot be subscribed to.",
        )

    now = datetime.now(timezone.utc)

    # Check if plan offers a free trial
    has_trial = plan.trial_period_days and plan.trial_period_days > 0

    # Abuse Prevention: Check if this user has already used a trial for this plan
    already_used_trial = False
    if has_trial:
        already_used_trial = (
            db.query(SubscriptionModel)
            .filter(
                SubscriptionModel.user_id == user.id,
                SubscriptionModel.plan_id == plan.id,
                SubscriptionModel.trial_start.isnot(None),
            )
            .first()
            is not None
        )

    if has_trial and not already_used_trial:
        trial_end = now + timedelta(days=plan.trial_period_days)
        new_sub = SubscriptionModel(
            user_id=user.id,
            plan_id=body.plan_id,
            status=SubscriptionStatus.TRIALING.value,
            price_amount=plan.price_amount,
            currency=plan.currency,
            billing_interval=plan.billing_interval,
            interval_count=plan.interval_count,
            trial_start=now,
            trial_end=trial_end,
            current_period_start=now,
            current_period_end=trial_end,
        )
        success_message = (
            f"Subscription created with a {plan.trial_period_days}-day free trial."
        )

    else:
        new_sub = SubscriptionModel(
            user_id=user.id,
            plan_id=body.plan_id,
            status=SubscriptionStatus.PENDING_PAYMENT.value,
            price_amount=plan.price_amount,
            currency=plan.currency,
            billing_interval=plan.billing_interval,
            interval_count=plan.interval_count,
        )
        success_message = (
            "Trial already redeemed for this plan. Subscription initiated with payment pending."
            if has_trial and already_used_trial
            else "Subscription initiated successfully. Payment Pending"
        )

    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)

    record_audit_log(
        db=db,
        action="CREATE_SUBSCRIPTION",
        target_type="SUBSCRIPTION",
        target_id=new_sub.id,
        user_id=user.id,
        details={"plan_id": plan.id, "plan_name": plan.name, "status": new_sub.status},
    )

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(new_sub).model_dump()

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message=success_message,
        data=responseData,
    )


def get_my_subscriptions(
    db: Session,
    user: UserModel,
    sub_status: Optional[str] = None,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    all_users: Optional[bool] = False,
):
    query = db.query(SubscriptionModel)

    if user.role == UserRole.ADMIN.value:
        if user_id is not None:
            query = query.filter(SubscriptionModel.user_id == user_id)
        elif not all_users:
            query = query.filter(SubscriptionModel.user_id == user.id)
    else:
        query = query.filter(SubscriptionModel.user_id == user.id)

    if sub_status:
        query = query.filter(SubscriptionModel.status == sub_status.upper())

    if search:
        search_filter = f"%{search}%"
        query = (
            query.join(SubscriptionModel.plan)
            .join(SubscriptionModel.user)
            .filter(
                (PlanPricingModel.name.ilike(search_filter))
                | (UserModel.full_name.ilike(search_filter))
                | (UserModel.email_address.ilike(search_filter))
            )
        )

    subs = query.order_by(SubscriptionModel.id.desc()).all()

    responseData = [
        SubscriptionReadSchema.model_validate(sub).model_dump() for sub in subs
    ]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscriptions fetched successfully",
        data=responseData,
    )


def get_subscription_by_id(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()

    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to access this subscription.",
        )

    data = SubscriptionReadSchema.model_validate(sub).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription fetched successfully",
        data=data,
    )


def cancel_subscription(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to cancel this subscription.",
        )

    if sub.status == SubscriptionStatus.CANCELLED.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Subscription is already cancelled.",
        )

    if sub.status == SubscriptionStatus.PENDING_PAYMENT.value:
        sub.status = SubscriptionStatus.CANCELLED.value
        sub.cancelled_at = datetime.now(timezone.utc)
        msg = "Pending subscription cancelled successfully."

    else:
        sub.cancel_at_period_end = True
        sub.cancelled_at = datetime.now(timezone.utc)
        msg = "Subscription will be cancelled at the end of the billing period."

    # Record cancellation in audit log
    record_audit_log(
        db=db,
        action="CANCEL_SUBSCRIPTION",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={
            "cancel_at_period_end": sub.cancel_at_period_end,
            "status": sub.status,
            "cancelled_at": str(sub.cancelled_at),
        },
    )

    db.commit()
    db.refresh(sub)

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(sub).model_dump()

    return ApiResponse(status=status.HTTP_200_OK, message=msg, data=responseData)


def preview_plan_change(id: int, new_plan_id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )
    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(status=status.HTTP_403_FORBIDDEN, message="Unauthorized")
    if sub.status not in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIALING.value,
    ]:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Only active or trialing subscriptions can change plans",
        )
    if sub.plan_id == new_plan_id:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="You are already subscribed to this plan",
        )
    new_plan = (
        db.query(PlanPricingModel).filter(PlanPricingModel.id == new_plan_id).first()
    )
    if not new_plan or not new_plan.is_active:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Target plan is not available"
        )

    current_plan = (
        db.query(PlanPricingModel).filter(PlanPricingModel.id == sub.plan_id).first()
    )
    proration_data = calculate_proration(sub=sub, new_plan=new_plan)

    responseData = {
        "subscription_id": sub.id,
        "current_plan_id": sub.plan_id,
        "current_plan_name": current_plan.name if current_plan else "Current Plan",
        "current_plan_price": sub.price_amount,
        "new_plan_id": new_plan.id,
        "new_plan_name": new_plan.name,
        "new_plan_price": new_plan.price_amount,
        "change_type": proration_data["change_type"],
        "effective_immediately": proration_data["effective_immediately"],
        "days_remaining_in_period": proration_data.get("days_remaining", 0),
        "total_days_in_period": proration_data.get("total_days", 30),
        "unused_credit": proration_data["unused_credit"],
        "new_plan_charge": proration_data["new_plan_charge"],
        "net_amount_due": proration_data["net_amount_due"],
        "currency": sub.currency,
        "effective_date": proration_data["effective_date"],
    }

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Plan change preview calculated successfully",
        data=responseData,
    )


def execute_plan_change(
    id: int, body: PlanChangeRequestSchema, db: Session, user: UserModel
):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(status=status.HTTP_403_FORBIDDEN, message="Unauthorized")

    if sub.status not in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIALING.value,
    ]:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Only active or trialing subscriptions can change plans",
        )

    if sub.plan_id == body.new_plan_id:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="You are already subscribed to this plan",
        )

    new_plan = (
        db.query(PlanPricingModel)
        .filter(PlanPricingModel.id == body.new_plan_id)
        .first()
    )

    if not new_plan or not new_plan.is_active:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Target plan is not available"
        )

    proration = calculate_proration(sub=sub, new_plan=new_plan)

    # 1. Downgrade: Schedule for current_period_end
    if proration["change_type"] == "DOWNGRADE":
        sub.pending_plan_id = new_plan.id

        # Audit log for scheduled downgrade
        record_audit_log(
            db=db,
            action="SCHEDULE_PLAN_DOWNGRADE",
            target_type="SUBSCRIPTION",
            target_id=sub.id,
            user_id=user.id,
            details={
                "current_plan_id": sub.plan_id,
                "pending_plan_id": new_plan.id,
                "effective_date": str(sub.current_period_end),
            },
        )

        db.commit()
        db.refresh(sub)

        # Invalidate cached subscriptions, dashboard, and analytics
        redis_cache.delete_pattern("subscription:*")
        redis_cache.delete_pattern("dashboard:*")
        redis_cache.delete_pattern("analytics:*")

        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Plan downgrade scheduled successfully for the end of the current billing cycle.",
            data={
                "subscription_id": sub.id,
                "current_plan_id": sub.plan_id,
                "pending_plan_id": sub.pending_plan_id,
                "effective_date": sub.current_period_end,
                "amount_due": 0,
            },
        )

    # 2. Upgrade: Initiate prorated payment checkout
    sub.pending_plan_id = new_plan.id
    db.commit()

    net_amount = proration["net_amount_due"]
    if net_amount > 0:
        receipt = f"upg_{sub.id}_{int(datetime.now(timezone.utc).timestamp())}"
        rzp_order = create_razorpay_order(
            amount=net_amount, currency=sub.currency, receipt=receipt
        )

        payment = PaymentModel(
            subscription_id=sub.id,
            user_id=user.id,
            provider="RAZORPAY",
            provider_order_id=rzp_order["id"],
            amount=net_amount,
            currency=sub.currency,
            status=PaymentStatus.CREATED.value,
        )
        db.add(payment)

        # Audit log for upgrade checkout initiation
        record_audit_log(
            db=db,
            action="INITIATE_PLAN_UPGRADE",
            target_type="SUBSCRIPTION",
            target_id=sub.id,
            user_id=user.id,
            details={
                "current_plan_id": sub.plan_id,
                "target_plan_id": new_plan.id,
                "prorated_amount": net_amount,
                "unused_credit": proration["unused_credit"],
            },
        )

        db.commit()
        db.refresh(payment)

        # Invalidate cached subscriptions, dashboard, and analytics
        redis_cache.delete_pattern("subscription:*")
        redis_cache.delete_pattern("dashboard:*")
        redis_cache.delete_pattern("analytics:*")

        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Upgrade initiated. Please complete the prorated payment.",
            data={
                "subscription_id": sub.id,
                "payment_id": payment.id,
                "razorpay_order_id": rzp_order["id"],
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
                "prorated_amount": net_amount,
                "currency": sub.currency,
                "unused_credit": proration["unused_credit"],
            },
        )
    else:
        # Net amount is 0; apply immediately
        sub.plan_id = new_plan.id
        sub.price_amount = new_plan.price_amount
        sub.pending_plan_id = None
        db.commit()
        db.refresh(sub)

        # Invalidate cached subscriptions, dashboard, and analytics
        redis_cache.delete_pattern("subscription:*")
        redis_cache.delete_pattern("dashboard:*")
        redis_cache.delete_pattern("analytics:*")

        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Plan upgraded immediately at no additional cost.",
            data={"subscription_id": sub.id, "plan_id": sub.plan_id},
        )


def pause_subscription(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to pause this subscription.",
        )

    if sub.status == SubscriptionStatus.PAUSED.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Subscription is already paused.",
        )

    if sub.status not in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIALING.value,
    ]:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message=f"Cannot pause a subscription in {sub.status} state. Only active or trialing subscriptions can be paused.",
        )

    previous_status = sub.status
    sub.status = SubscriptionStatus.PAUSED.value

    record_audit_log(
        db=db,
        action="PAUSE_SUBSCRIPTION",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={"previous_status": previous_status, "status": sub.status},
    )

    db.commit()
    db.refresh(sub)

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(sub).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription paused successfully. Recurring billing and renewals are suspended.",
        data=responseData,
    )


def resume_subscription(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to resume this subscription.",
        )

    if sub.status != SubscriptionStatus.PAUSED.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Only paused subscriptions can be resumed.",
        )

    sub.status = SubscriptionStatus.ACTIVE.value

    record_audit_log(
        db=db,
        action="RESUME_SUBSCRIPTION",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={"previous_status": "PAUSED", "status": sub.status},
    )

    db.commit()
    db.refresh(sub)

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(sub).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription resumed successfully. Recurring billing has been restored.",
        data=responseData,
    )


def cancel_downgrade(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to modify this subscription.",
        )

    if not sub.pending_plan_id:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="No scheduled plan downgrade found for this subscription.",
        )

    cancelled_pending_id = sub.pending_plan_id
    sub.pending_plan_id = None

    record_audit_log(
        db=db,
        action="CANCEL_PLAN_DOWNGRADE",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={"cancelled_pending_plan_id": cancelled_pending_id},
    )

    db.commit()
    db.refresh(sub)

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(sub).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Scheduled downgrade cancelled. You will continue on your current plan.",
        data=responseData,
    )


def reactivate_subscription(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to reactivate this subscription.",
        )

    if not sub.cancel_at_period_end and sub.status != SubscriptionStatus.CANCELLED.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Subscription is not pending cancellation or cancelled.",
        )

    now = datetime.now(timezone.utc)
    if sub.current_period_end:
        period_end = (
            sub.current_period_end.replace(tzinfo=timezone.utc)
            if sub.current_period_end.tzinfo is None
            else sub.current_period_end
        )
        if period_end < now:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Subscription billing period has already ended. Please create a new subscription.",
            )

    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.status = SubscriptionStatus.ACTIVE.value

    record_audit_log(
        db=db,
        action="REACTIVATE_SUBSCRIPTION",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={"status": sub.status, "cancel_at_period_end": False},
    )

    db.commit()
    db.refresh(sub)

    # Invalidate cached subscriptions, dashboard, and analytics
    redis_cache.delete_pattern("subscription:*")
    redis_cache.delete_pattern("dashboard:*")
    redis_cache.delete_pattern("analytics:*")

    responseData = SubscriptionReadSchema.model_validate(sub).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription reactivated successfully. Auto-renewal has been re-enabled.",
        data=responseData,
    )


_AUDIT_ACTION_META = {
    "CREATE_SUBSCRIPTION": (
        "Subscription created",
        "Subscription initialized.",
        "neutral",
    ),
    "CANCEL_SUBSCRIPTION": (
        "Cancellation scheduled",
        "Subscription will cancel at the end of the current cycle.",
        "danger",
    ),
    "SCHEDULE_PLAN_DOWNGRADE": (
        "Downgrade scheduled",
        "Plan change scheduled for the end of this billing cycle.",
        "warning",
    ),
    "INITIATE_PLAN_UPGRADE": (
        "Plan upgrade initiated",
        "Prorated upgrade checkout initiated.",
        "info",
    ),
    "PAUSE_SUBSCRIPTION": (
        "Subscription paused",
        "Recurring billing and renewals suspended.",
        "warning",
    ),
    "RESUME_SUBSCRIPTION": (
        "Subscription resumed",
        "Recurring billing and active access restored.",
        "success",
    ),
    "CANCEL_PLAN_DOWNGRADE": (
        "Downgrade cancelled",
        "Scheduled downgrade cancelled; current plan retained.",
        "info",
    ),
    "REACTIVATE_SUBSCRIPTION": (
        "Subscription reactivated",
        "Auto-renewal re-enabled for the active cycle.",
        "success",
    ),
    "UPDATE_PAYMENT_METHOD": (
        "Payment method updated",
        "Default payment method updated.",
        "info",
    ),
}


def _format_inr(amount_paise: int) -> str:
    rupees = amount_paise // 100
    return f"₹{rupees:,}"


def _build_subscription_activity(
    sub: SubscriptionModel,
    db: Session,
    invoices: Optional[List[InvoiceModel]] = None,
) -> List[SubscriptionActivityItemSchema]:
    events: List[SubscriptionActivityItemSchema] = []

    audit_rows = (
        db.query(AuditLogModel)
        .filter(
            AuditLogModel.target_type == "SUBSCRIPTION",
            AuditLogModel.target_id == sub.id,
        )
        .order_by(AuditLogModel.created_at.desc())
        .all()
    )

    has_create_audit = False
    for log in audit_rows:
        if log.action == "CREATE_SUBSCRIPTION":
            has_create_audit = True
        default_title, default_desc, variant = _AUDIT_ACTION_META.get(
            log.action,
            (log.action.replace("_", " ").title(), "Subscription updated.", "neutral"),
        )
        details = log.details or {}
        description = default_desc
        if log.action == "CREATE_SUBSCRIPTION" and details.get("plan_name"):
            description = f"Started on the {details['plan_name']} plan."
        elif log.action == "UPDATE_PAYMENT_METHOD" and details.get("label"):
            description = f"Updated payment method to {details['label']}."

        events.append(
            SubscriptionActivityItemSchema(
                id=f"audit_{log.id}",
                action=log.action,
                title=default_title,
                description=description,
                timestamp=log.created_at,
                variant=variant,
            )
        )

    sub_invoices = (
        invoices
        if invoices is not None
        else db.query(InvoiceModel)
        .filter(InvoiceModel.subscription_id == sub.id)
        .order_by(InvoiceModel.created_at.desc())
        .all()
    )
    for inv in sub_invoices:
        reason = (inv.billing_reason or "").upper()
        if reason == "SUBSCRIPTION_CYCLE":
            title = "Subscription renewed"
        elif reason == "PLAN_UPGRADE":
            title = "Plan upgraded"
        else:
            title = "Subscription activated"

        events.append(
            SubscriptionActivityItemSchema(
                id=f"invoice_{inv.id}",
                action=f"INVOICE_{inv.status}",
                title=title,
                description=f"{_format_inr(inv.total_amount)} {inv.status.lower()}, invoice {inv.invoice_number}.",
                timestamp=inv.paid_at or inv.created_at,
                variant="success" if inv.status == "PAID" else "warning",
            )
        )

    if not has_create_audit:
        plan_name = sub.plan.name if sub.plan else f"Plan #{sub.plan_id}"
        events.append(
            SubscriptionActivityItemSchema(
                id=f"sub_created_{sub.id}",
                action="CREATE_SUBSCRIPTION",
                title="Subscription created",
                description=f"Started on the {plan_name} plan.",
                timestamp=sub.created_at,
                variant="neutral",
            )
        )

    events.sort(key=lambda e: e.timestamp.replace(tzinfo=timezone.utc) if e.timestamp.tzinfo is None else e.timestamp, reverse=True)
    return events


def _resolve_payment_method(
    sub: SubscriptionModel,
    latest_payment: Optional[PaymentModel],
    db: Session,
) -> Optional[PaymentMethodReadSchema]:
    saved = (
        db.query(SubscriptionPaymentMethodModel)
        .filter(SubscriptionPaymentMethodModel.subscription_id == sub.id)
        .first()
    )
    if saved:
        return PaymentMethodReadSchema.model_validate(saved)

    if latest_payment:
        ref = latest_payment.provider_payment_id or latest_payment.provider_order_id
        return PaymentMethodReadSchema(
            method_type=latest_payment.provider,
            label=f"{latest_payment.provider.title()} ({ref})",
            last4=None,
            expiry=None,
            updated_at=latest_payment.updated_at,
        )

    return None


def get_subscription_activity(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to view this subscription's activity.",
        )

    events = _build_subscription_activity(sub=sub, db=db)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription activity fetched successfully",
        data=[e.model_dump() for e in events],
    )


def get_subscription_details(id: int, db: Session, user: UserModel):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to access this subscription.",
        )

    invoices = (
        db.query(InvoiceModel)
        .filter(InvoiceModel.subscription_id == sub.id)
        .order_by(InvoiceModel.id.desc())
        .all()
    )
    latest_payment = (
        db.query(PaymentModel)
        .filter(PaymentModel.subscription_id == sub.id)
        .order_by(PaymentModel.id.desc())
        .first()
    )
    payment_method = _resolve_payment_method(
        sub=sub, latest_payment=latest_payment, db=db
    )
    activity = _build_subscription_activity(sub=sub, db=db, invoices=invoices)

    payload = SubscriptionDetailsReadSchema(
        subscription=SubscriptionReadSchema.model_validate(sub),
        invoices=[InvoiceReadSchema.model_validate(inv) for inv in invoices],
        latest_payment=(
            PaymentReadSchema.model_validate(latest_payment)
            if latest_payment
            else None
        ),
        payment_method=payment_method,
        activity=activity,
    ).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription details fetched successfully",
        data=payload,
    )


def update_subscription_payment_method(
    id: int,
    body: PaymentMethodUpdateSchema,
    db: Session,
    user: UserModel,
):
    sub = db.query(SubscriptionModel).filter(SubscriptionModel.id == id).first()
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    if sub.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to update this subscription's payment method.",
        )

    pm = (
        db.query(SubscriptionPaymentMethodModel)
        .filter(SubscriptionPaymentMethodModel.subscription_id == sub.id)
        .first()
    )
    if pm:
        pm.method_type = body.method_type
        pm.label = body.label
        pm.last4 = body.last4
        pm.expiry = body.expiry
    else:
        pm = SubscriptionPaymentMethodModel(
            subscription_id=sub.id,
            user_id=sub.user_id,
            method_type=body.method_type,
            label=body.label,
            last4=body.last4,
            expiry=body.expiry,
        )
        db.add(pm)

    record_audit_log(
        db=db,
        action="UPDATE_PAYMENT_METHOD",
        target_type="SUBSCRIPTION",
        target_id=sub.id,
        user_id=user.id,
        details={"method_type": body.method_type, "label": body.label},
    )

    db.commit()
    db.refresh(pm)

    redis_cache.delete_pattern("subscription:*")

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Payment method updated successfully",
        data=PaymentMethodReadSchema.model_validate(pm).model_dump(),
    )

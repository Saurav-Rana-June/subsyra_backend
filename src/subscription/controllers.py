from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from fastapi import status
from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.subscription.models import SubscriptionModel
from src.plans_pricing.models import PlanPricingModel
from src.utils.proration import calculate_proration
from src.subscription.dtos import (
    SubscriptionStatus,
    SubscriptionCreateSchema,
    SubscriptionReadSchema,
    PlanChangeRequestSchema,
)
from src.utils.payment_services import create_razorpay_order
from src.payment.models import PaymentModel, PaymentStatus
from src.utils.settings import settings
from src.audit_logs.services import record_audit_log


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

    responseData = SubscriptionReadSchema.model_validate(new_sub).model_dump()

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message=success_message,
        data=responseData,
    )


def get_my_subscriptions(db: Session, user: UserModel):
    my_subs = (
        db.query(SubscriptionModel).filter(SubscriptionModel.user_id == user.id).all()
    )

    responseData = [
        SubscriptionReadSchema.model_validate(sub).model_dump() for sub in my_subs
    ]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="All subscriptions fetched sucessfully",
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
    proration_data = calculate_proration(sub=sub, new_plan=new_plan)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Plan change preview calculated successfully",
        data=proration_data,
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
        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Plan upgraded immediately at no additional cost.",
            data={"subscription_id": sub.id, "plan_id": sub.plan_id},
        )

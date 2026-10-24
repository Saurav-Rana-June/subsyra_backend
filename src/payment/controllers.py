import json
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from fastapi import status, HTTPException
from src.utils.helpers import calculate_period_end
from src.utils.responses import ApiResponse
from src.utils.settings import settings
from src.utils.payment_services import (
    create_razorpay_order,
    verify_razorpay_signature,
    verify_razorpay_webhook_signature,
    create_razorpay_refund,
)
from src.users.models import UserModel, UserRole
from src.plans_pricing.models import PlanPricingModel
from src.subscription.models import SubscriptionModel, SubscriptionStatus
from src.payment.models import (
    PaymentModel,
    PaymentStatus,
    WebhookEventModel,
    RefundModel,
    RefundStatus,
)
from src.payment.dtos import (
    PaymentCheckoutRequestSchema,
    PaymentVerifySchema,
    PaymentReadSchema,
    RefundRequestSchema,
    RefundReadSchema,
)
from sqlalchemy.exc import IntegrityError
from src.utils.invoices_services import create_invoice_for_payment
from src.utils.subscription_services import handle_failed_renewal
from src.audit_logs.services import record_audit_log


def initiate_checkout(body: PaymentCheckoutRequestSchema, db: Session, user: UserModel):
    # 1. Fetch subscription
    sub = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.id == body.subscription_id)
        .first()
    )
    if not sub:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Subscription not found"
        )

    # 2. Ownership check
    if sub.user_id != user.id:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to pay for this subscription.",
        )

    # 3. Status check
    if sub.status == SubscriptionStatus.ACTIVE.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="This subscription is already active.",
        )
    if sub.status == SubscriptionStatus.CANCELLED.value:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="This subscription has been cancelled.",
        )

    # 4. Generate order with Razorpay
    receipt = f"sub_{sub.id}_{int(datetime.now().timestamp())}"
    rzp_order = create_razorpay_order(
        receipt=receipt, currency=sub.currency, amount=sub.price_amount
    )

    # 5. Persist internal payment record
    new_payment = PaymentModel(
        subscription_id=sub.id,
        user_id=user.id,
        provider="RAZORPAY",
        provider_order_id=rzp_order["id"],
        amount=sub.price_amount,
        currency=sub.currency,
        status=PaymentStatus.CREATED.value,
    )

    db.add(new_payment)
    db.commit()
    db.refresh(new_payment)

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Checkout initiated successfully",
        data={
            "subscription_id": sub.id,
            "payment_id": new_payment.id,
            "razorpay_order_id": rzp_order["id"],
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            "amount": new_payment.amount,
            "currency": new_payment.currency,
        },
    )


def verify_payment(body: PaymentVerifySchema, db: Session, user: UserModel):
    # 1. Cryptographic signature check
    is_valid = verify_razorpay_signature(
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
    )

    # 2. Fetch payment record
    payment = (
        db.query(PaymentModel)
        .filter(PaymentModel.provider_order_id == body.razorpay_order_id)
        .first()
    )

    if not payment:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Payment order not found"
        )

    # 3. Ownership check
    if payment.user_id != user.id:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Unauthorized payment verification",
        )

    # 4. Handle signature failure
    if not is_valid:
        payment.status = PaymentStatus.FAILED.value
        payment.failure_reason = "Cryptographic signature mismatch"
        db.commit()
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Payment verification failed: Signature mismatch",
        )

    # 5. Idempotency check: Already activated?
    if payment.status == PaymentStatus.SUCCESS.value:
        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Payment already verified and subscription is active.",
        )

    # 6. Atomic activation of Subscription & Payment
    sub = (
        db.query(SubscriptionModel)
        .filter(SubscriptionModel.id == payment.subscription_id)
        .first()
    )

    # Update payment
    payment.status = PaymentStatus.SUCCESS.value
    payment.provider_payment_id = body.razorpay_payment_id

    # Update subscription
    now = datetime.now(timezone.utc)

    # Check for plan upgrade settlement vs new subscription activation
    if sub.pending_plan_id:
        pending_plan = (
            db.query(PlanPricingModel)
            .filter(PlanPricingModel.id == sub.pending_plan_id)
            .first()
        )
        if pending_plan:
            sub.plan_id = pending_plan.id
            sub.price_amount = pending_plan.price_amount
            sub.currency = pending_plan.currency
            sub.billing_interval = pending_plan.billing_interval
            sub.interval_count = pending_plan.interval_count
            sub.pending_plan_id = None

        sub.status = SubscriptionStatus.ACTIVE.value
        sub.grace_period_end = None
        sub.renewal_retry_count = 0
        # For upgrades on an already active subscription, retain current_period_end
        if not sub.current_period_start or not sub.current_period_end:
            sub.current_period_start = now
            sub.current_period_end = calculate_period_end(
                start_date=now, interval=sub.billing_interval, count=sub.interval_count
            )

        create_invoice_for_payment(
            db=db, payment=payment, subscription=sub, billing_reason="PLAN_UPGRADE"
        )
    else:
        was_past_due = sub.status == SubscriptionStatus.PAST_DUE.value
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.grace_period_end = None
        sub.renewal_retry_count = 0
        sub.current_period_start = now
        sub.current_period_end = calculate_period_end(
            start_date=now, interval=sub.billing_interval, count=sub.interval_count
        )
        create_invoice_for_payment(
            db=db,
            payment=payment,
            subscription=sub,
            billing_reason=(
                "SUBSCRIPTION_CYCLE" if was_past_due else "SUBSCRIPTION_CREATE"
            ),
        )

    db.commit()
    db.refresh(payment)
    db.refresh(sub)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Payment verified successfully. Subscription is now ACTIVE!",
        data={
            "payment_id": payment.id,
            "subscription_id": sub.id,
            "status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
        },
    )


def get_payment_by_id(id: int, db: Session, user: UserModel):
    payment = db.query(PaymentModel).filter(PaymentModel.id == id).first()
    if not payment:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Payment not found"
        )
    # Ownership check
    if payment.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to view this payment.",
        )
    data = PaymentReadSchema.model_validate(payment).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK, message="Payment fetched successfully", data=data
    )


async def handle_razorpay_webhook(
    request_body: bytes, signature: str, db: Session, event_id_header: str = None
):
    # 1. Verify webhook signature against raw bytes
    try:
        body_str = request_body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload encoding"
        )

    if not verify_razorpay_webhook_signature(body_str, signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature"
        )

    # 2. Parse event payload
    try:
        event_data = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload"
        )

    event_type = event_data.get("event")

    event_id = event_id_header or event_data.get("id") or event_data.get("event_id")

    if event_id:
        existing_event = (
            db.query(WebhookEventModel)
            .filter(WebhookEventModel.event_id == event_id)
            .first()
        )
        if existing_event:
            return {"status": "ok", "message": "Event already processed"}

    # 4. Atomic Processing & Transaction Management
    processing_status = "PROCESSED"

    try:
        # Extract payment entity safely
        payment_entity = (
            event_data.get("payload", {}).get("payment", {}).get("entity", {})
        )
        order_id = payment_entity.get("order_id")
        payment_id = payment_entity.get("id")

        if event_type in ["payment.captured", "order.paid"]:
            if not order_id:
                processing_status = "UNMATCHED"
            else:
                payment = (
                    db.query(PaymentModel)
                    .filter(PaymentModel.provider_order_id == order_id)
                    .first()
                )

                if not payment:
                    processing_status = "UNMATCHED"
                elif payment.status != PaymentStatus.SUCCESS.value:
                    webhook_amount = payment_entity.get("amount")
                    webhook_currency = payment_entity.get("currency")

                    # Validate amount and currency
                    if (
                        webhook_amount != payment.amount
                        or webhook_currency != payment.currency
                    ):
                        payment.status = PaymentStatus.FAILED.value
                        payment.failure_reason = (
                            f"Amount/Currency mismatch: Expected {payment.amount} {payment.currency}, "
                            f"got {webhook_amount} {webhook_currency}"
                        )
                    else:
                        # Mark payment success
                        payment.status = PaymentStatus.SUCCESS.value
                        payment.provider_payment_id = payment_id

                        # Activate or upgrade subscription
                        sub = (
                            db.query(SubscriptionModel)
                            .filter(SubscriptionModel.id == payment.subscription_id)
                            .first()
                        )

                        if sub:
                            now = datetime.now(timezone.utc)
                            if sub.pending_plan_id:
                                pending_plan = (
                                    db.query(PlanPricingModel)
                                    .filter(PlanPricingModel.id == sub.pending_plan_id)
                                    .first()
                                )
                                if pending_plan:
                                    sub.plan_id = pending_plan.id
                                    sub.price_amount = pending_plan.price_amount
                                    sub.currency = pending_plan.currency
                                    sub.billing_interval = pending_plan.billing_interval
                                    sub.interval_count = pending_plan.interval_count
                                    sub.pending_plan_id = None

                                sub.status = SubscriptionStatus.ACTIVE.value
                                if (
                                    not sub.current_period_start
                                    or not sub.current_period_end
                                ):
                                    sub.current_period_start = now
                                    sub.current_period_end = calculate_period_end(
                                        start_date=now,
                                        interval=sub.billing_interval,
                                        count=sub.interval_count,
                                    )
                                create_invoice_for_payment(
                                    db=db,
                                    payment=payment,
                                    subscription=sub,
                                    billing_reason="PLAN_UPGRADE",
                                )
                            elif sub.status in [
                                SubscriptionStatus.PENDING_PAYMENT.value,
                                SubscriptionStatus.TRIALING.value,
                                SubscriptionStatus.PAST_DUE.value,
                                SubscriptionStatus.EXPIRED.value,
                            ]:
                                was_past_due = (
                                    sub.status == SubscriptionStatus.PAST_DUE.value
                                )
                                sub.status = SubscriptionStatus.ACTIVE.value
                                sub.grace_period_end = None
                                sub.renewal_retry_count = 0
                                sub.current_period_start = now
                                sub.current_period_end = calculate_period_end(
                                    start_date=now,
                                    interval=sub.billing_interval,
                                    count=sub.interval_count,
                                )
                                create_invoice_for_payment(
                                    db=db,
                                    payment=payment,
                                    subscription=sub,
                                    billing_reason=(
                                        "SUBSCRIPTION_CYCLE"
                                        if was_past_due
                                        else "SUBSCRIPTION_CREATE"
                                    ),
                                )

        elif event_type == "payment.failed":
            if not order_id:
                processing_status = "UNMATCHED"
            else:
                payment = (
                    db.query(PaymentModel)
                    .filter(PaymentModel.provider_order_id == order_id)
                    .first()
                )

                if not payment:
                    processing_status = "UNMATCHED"
                # Prevent out-of-order overwrite: Never mark FAILED if already SUCCESS
                elif payment.status != PaymentStatus.SUCCESS.value:
                    payment.status = PaymentStatus.FAILED.value
                    payment.failure_reason = payment_entity.get(
                        "error_description", "Payment failed"
                    )

                    # Trigger dunning for active or past-due subscriptions
                    sub = (
                        db.query(SubscriptionModel)
                        .filter(SubscriptionModel.id == payment.subscription_id)
                        .first()
                    )
                    if sub and sub.status in [
                        SubscriptionStatus.ACTIVE.value,
                        SubscriptionStatus.PAST_DUE.value,
                    ]:
                        handle_failed_renewal(sub=sub, db=db)

        else:
            # Unsupported event (e.g. refund.created, dispute, etc.)
            processing_status = "SKIPPED"

        # Record this event in WebhookEventModel with accurate audit status
        if event_id:
            new_event = WebhookEventModel(
                event_id=event_id,
                event_type=event_type or "unknown",
                status=processing_status,
            )
            db.add(new_event)

        # Single atomic commit for all modifications
        db.commit()

    except IntegrityError:
        db.rollback()
        # Caught concurrent race condition where duplicate event was inserted simultaneously
        return {"status": "ok", "message": "Event already processed concurrently"}

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process webhook event",
        )

    return {"status": "ok", "event_status": processing_status}


def issue_refund(
    payment_id: int, body: RefundRequestSchema, db: Session, user: UserModel
):
    # 1. Admin RBAC check
    if user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="Only administrators can issue refunds.",
        )

    # 2. Fetch payment
    payment = db.query(PaymentModel).filter(PaymentModel.id == payment_id).first()
    if not payment:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Payment not found."
        )

    if payment.status not in [
        PaymentStatus.SUCCESS.value,
        PaymentStatus.PARTIALLY_REFUNDED.value,
    ]:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Only successful or partially refunded payments can be refunded.",
        )

    if not payment.provider_payment_id:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Payment has no provider transaction reference.",
        )

    # 3. Calculate remaining unrefunded balance
    total_refunded = (
        db.query(func.coalesce(func.sum(RefundModel.amount), 0))
        .filter(
            RefundModel.payment_id == payment.id,
            RefundModel.status != RefundStatus.FAILED.value,
        )
        .scalar()
    )
    remaining_balance = payment.amount - total_refunded

    if remaining_balance <= 0:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Payment has already been fully refunded.",
        )

    refund_amount = body.amount if body.amount is not None else remaining_balance

    if refund_amount > remaining_balance:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message=f"Refund amount ({refund_amount}) exceeds remaining refundable balance ({remaining_balance}).",
        )

    # 4. Process refund with Razorpay
    try:
        rzp_refund = create_razorpay_refund(
            payment_id=payment.provider_payment_id,
            amount=refund_amount,
            notes={"reason": body.reason or "Admin initiated refund"},
        )

    except Exception as e:
        return ApiResponse(
            status=status.HTTP_502_BAD_GATEWAY,
            message=f"Razorpay refund gateway error: {str(e)}",
        )

    # 5. Save Refund Record
    new_refund = RefundModel(
        payment_id=payment.id,
        user_id=payment.user_id,
        provider_refund_id=rzp_refund.get("id"),
        amount=refund_amount,
        currency=payment.currency or "INR",
        reason=body.reason,
        status=RefundStatus.PROCESSED.value,
    )
    db.add(new_refund)

    # 6. Update payment status
    new_remaining = remaining_balance - refund_amount
    if new_remaining <= 0:
        payment.status = PaymentStatus.REFUNDED.value
    else:
        payment.status = PaymentStatus.PARTIALLY_REFUNDED.value

    # 7. If fully refunded, cancel the subscription and revoke access
    if new_remaining <= 0:
        sub = (
            db.query(SubscriptionModel)
            .filter(SubscriptionModel.id == payment.subscription_id)
            .first()
        )
        if sub and sub.status in [
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.TRIALING.value,
            SubscriptionStatus.PAST_DUE.value,
        ]:
            sub.status = SubscriptionStatus.CANCELLED.value
            sub.cancelled_at = datetime.now(timezone.utc)

    # Record refund in audit log
    record_audit_log(
        db=db,
        action="ISSUE_REFUND",
        target_type="PAYMENT",
        target_id=payment.id,
        user_id=user.id,
        details={
            "refund_id": new_refund.id,
            "provider_refund_id": new_refund.provider_refund_id,
            "amount": refund_amount,
            "currency": new_refund.currency,
            "reason": body.reason,
            "is_full_refund": new_remaining <= 0,
        },
    )

    db.commit()
    db.refresh(new_refund)

    response_data = RefundReadSchema.model_validate(new_refund).model_dump()
    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Refund processed successfully.",
        data=response_data,
    )


def get_payment_refunds(payment_id: int, db: Session, user: UserModel):
    payment = db.query(PaymentModel).filter(PaymentModel.id == payment_id).first()
    if not payment:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Payment not found."
        )

    if payment.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to view refunds for this payment.",
        )

    refunds = db.query(RefundModel).filter(RefundModel.payment_id == payment_id).all()

    responseData = [RefundReadSchema.model_validate(r).model_dump() for r in refunds]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Refunds fetched successfully.",
        data=responseData,
    )

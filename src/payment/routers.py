from fastapi import APIRouter, Depends, status, Request, Header, HTTPException
from sqlalchemy.orm import Session
from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.payment import controllers
from src.payment.dtos import (
    PaymentCheckoutRequestSchema,
    PaymentVerifySchema,
    RefundRequestSchema,
)

payment_routes = APIRouter(prefix="/payments", tags=["Payments"])


@payment_routes.post("/checkout", status_code=status.HTTP_201_CREATED)
def checkout(
    body: PaymentCheckoutRequestSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.initiate_checkout(body=body, db=db, user=user)


@payment_routes.post("/verify", status_code=status.HTTP_200_OK)
def verify(
    body: PaymentVerifySchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.verify_payment(body=body, db=db, user=user)


@payment_routes.get("/{id}", status_code=status.HTTP_200_OK)
def get_payment(
    id: int, db: Session = Depends(get_db), user: UserModel = Depends(is_authenticated)
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_payment_by_id(id=id, db=db, user=user)


@payment_routes.post("/webhook/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None),
    x_razorpay_event_id: str = Header(None, alias="x-razorpay-event-id"),
    db: Session = Depends(get_db),
):
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature header"
        )

    body_bytes = await request.body()

    return await controllers.handle_razorpay_webhook(
        request_body=body_bytes,
        signature=x_razorpay_signature,
        event_id_header=x_razorpay_event_id,
        db=db,
    )


@payment_routes.post("/{id}/refund", status_code=status.HTTP_201_CREATED)
def refund_payment(
    id: int,
    body: RefundRequestSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.issue_refund(payment_id=id, body=body, db=db, user=user)


@payment_routes.get("/{id}/refunds", status_code=status.HTTP_200_OK)
def get_refunds(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_payment_refunds(payment_id=id, db=db, user=user)

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from src.payment.models import PaymentStatus, RefundStatus


class PaymentCheckoutRequestSchema(BaseModel):
    subscription_id: int


class PaymentVerifySchema(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentReadSchema(BaseModel):
    id: int
    subscription_id: int
    user_id: int
    provider: str
    provider_order_id: str
    provider_payment_id: Optional[str] = None
    amount: int
    currency: str
    status: PaymentStatus
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RefundRequestSchema(BaseModel):
    amount: Optional[int] = Field(
        default=None,
        gt=0,
        description="Amount to refund in paise. If omitted, refunds the full unrefunded balance.",
    )
    reason: Optional[str] = Field(default=None, max_length=255)


class RefundReadSchema(BaseModel):
    id: int
    payment_id: int
    user_id: int
    provider_refund_id: Optional[str] = None
    amount: int
    currency: str
    reason: Optional[str] = None
    status: RefundStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

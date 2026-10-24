from enum import Enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.utils.db import Base
from src.users.models import UserModel
from src.subscription.models import SubscriptionModel


class PaymentStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class PaymentModel(Base):
    __tablename__ = "payments_table"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(
        Integer, ForeignKey("subscriptions_table.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users_table.id"), nullable=False, index=True)
    provider = Column(String, default="RAZORPAY", nullable=False)
    provider_order_id = Column(String, unique=True, nullable=False, index=True)
    provider_payment_id = Column(String, unique=True, nullable=True, index=True)
    amount = Column(Integer, nullable=False)
    currency = Column(String(3), default="INR", nullable=True)
    status = Column(String, default=PaymentStatus.CREATED.value, nullable=False)
    failure_reason = Column(String, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    user = relationship("UserModel")
    subscription = relationship("SubscriptionModel")


class WebhookEventModel(Base):
    __tablename__ = "webhook_events_table"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    status = Column(String, default="PROCESSED", nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class RefundModel(Base):
    __tablename__ = "refunds_table"

    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(
        Integer, ForeignKey("payments_table.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users_table.id"), nullable=False, index=True)
    provider_refund_id = Column(String, unique=True, nullable=True, index=True)
    amount = Column(Integer, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, default=RefundStatus.PENDING.value, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    payment = relationship("PaymentModel")
    user = relationship("UserModel")

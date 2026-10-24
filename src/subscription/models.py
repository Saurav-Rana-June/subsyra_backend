from src.utils.db import Base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, JSON
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy.orm import relationship
from src.users.models import UserModel
from src.plans_pricing.models import PlanPricingModel


class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    TRIALING = "TRIALING"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SubscriptionModel(Base):
    __tablename__ = "subscriptions_table"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users_table.id"), nullable=False, index=True)
    plan_id = Column(
        Integer, ForeignKey("plans_pricing_table.id"), nullable=False, index=True
    )
    status = Column(
        String, default=SubscriptionStatus.PENDING_PAYMENT.value, nullable=False
    )
    price_amount = Column(Integer, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    billing_interval = Column(String, nullable=False)
    interval_count = Column(Integer, default=1, nullable=False)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    pending_plan_id = Column(
        Integer, ForeignKey("plans_pricing_table.id"), nullable=True, index=True
    )
    grace_period_end = Column(DateTime, nullable=True)
    renewal_retry_count = Column(
        Integer, default=0, server_default="0", nullable=False
    )
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
    plan = relationship("PlanPricingModel", foreign_keys=[plan_id])
    pending_plan = relationship("PlanPricingModel", foreign_keys=[pending_plan_id])

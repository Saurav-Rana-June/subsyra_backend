from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.utils.db import Base
from src.users.models import UserModel
from src.subscription.models import SubscriptionModel
from src.payment.models import PaymentModel


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class InvoiceModel(Base):
    __tablename__ = "invoices_table"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users_table.id"), nullable=False, index=True)
    subscription_id = Column(
        Integer, ForeignKey("subscriptions_table.id"), nullable=False, index=True
    )
    payment_id = Column(
        Integer, ForeignKey("payments_table.id"), nullable=True, index=True
    )
    subtotal = Column(Integer, nullable=False)
    tax_amount = Column(Integer, default=0, nullable=False)
    total_amount = Column(Integer, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    status = Column(String, default=InvoiceStatus.PAID.value, nullable=False)
    billing_reason = Column(String, default="SUBSCRIPTION_CREATE", nullable=False)
    paid_at = Column(DateTime, nullable=True)
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
    payment = relationship("PaymentModel")

    @property
    def plan_name(self) -> Optional[str]:
        if self.subscription and self.subscription.plan:
            return self.subscription.plan.name
        return None

    @property
    def due_date(self) -> Optional[datetime]:
        if self.paid_at:
            return self.paid_at
        if self.created_at:
            return self.created_at + timedelta(days=7)
        return None

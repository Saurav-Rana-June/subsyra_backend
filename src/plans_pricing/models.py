from src.utils.db import Base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, JSON
from datetime import datetime, timezone


class PlanPricingModel(Base):
    __tablename__ = "plans_pricing_table"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True, unique=True)
    description = Column(String, nullable=True)
    price_amount = Column(Integer, nullable=False)
    currency = Column(String(3), default="INR", nullable=False)
    billing_interval = Column(String, nullable=False)
    interval_count = Column(Integer, default=1, nullable=False)
    features = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    trial_period_days = Column(
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

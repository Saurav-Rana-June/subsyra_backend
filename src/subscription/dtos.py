from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from src.subscription.models import SubscriptionStatus
from src.plans_pricing.dtos import PlanPricingReadSchema
from src.users.dtos import UserReadSchema


class SubscriptionCreateSchema(BaseModel):
    plan_id: int


class SubscriptionReadSchema(BaseModel):
    id: int
    user_id: int
    plan_id: int
    status: SubscriptionStatus
    price_amount: int
    currency: str
    billing_interval: str
    interval_count: int
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool
    cancelled_at: Optional[datetime] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    pending_plan_id: Optional[int] = None
    grace_period_end: Optional[datetime] = None
    renewal_retry_count: int = 0
    created_at: datetime
    updated_at: datetime
    plan: Optional[PlanPricingReadSchema] = None
    pending_plan: Optional[PlanPricingReadSchema] = None
    user: Optional[UserReadSchema] = None

    model_config = {"from_attributes": True}


class PlanChangeRequestSchema(BaseModel):
    new_plan_id: int


class PlanChangePreviewResponseSchema(BaseModel):
    subscription_id: int
    current_plan_id: int
    current_plan_name: str
    current_plan_price: int
    new_plan_id: int
    new_plan_name: str
    new_plan_price: int
    change_type: Literal["UPGRADE", "DOWNGRADE"]
    effective_immediately: bool
    days_remaining_in_period: int
    total_days_in_period: int
    unused_credit: int
    new_plan_charge: int
    net_amount_due: int
    currency: str
    effective_date: datetime

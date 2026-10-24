from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime


class PlanPricingCreateSchema(BaseModel):
    name: str
    description: Optional[str] = None
    # gt=0 ensures price is strictly positive (e.g. at least 1 paisa)
    price_amount: int = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    # Literal restricts the value strictly to "month" or "year"
    billing_interval: Literal["month", "year"]
    interval_count: int = Field(default=1, ge=1)
    features: Optional[Dict[str, Any]] = None
    trial_period_days: Optional[int] = Field(default=0, ge=0)


class PlanPricingReadSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price_amount: int
    currency: str
    billing_interval: str
    interval_count: int
    features: Optional[Dict[str, Any]] = None
    is_active: bool
    trial_period_days: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PlanPricingUpdateSchema(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_amount: Optional[int] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    billing_interval: Optional[Literal["month", "year"]] = None
    interval_count: Optional[int] = Field(default=None, ge=1)
    features: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    trial_period_days: Optional[int] = Field(default=None, ge=0)

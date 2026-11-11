from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field
from src.users.dtos import UserReadSchema


class InvoiceReadSchema(BaseModel):
    id: int
    invoice_number: str
    user_id: int
    subscription_id: int
    payment_id: Optional[int] = None
    subtotal: int
    tax_amount: int
    total_amount: int
    currency: str
    status: str
    billing_reason: str
    paid_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    created_at: datetime
    plan_name: Optional[str] = None
    user: Optional[UserReadSchema] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceCreateSchema(BaseModel):
    user_id: int
    subscription_id: int
    subtotal: int = Field(..., gt=0, description="Base amount in paise")
    tax_amount: int = Field(default=0, ge=0, description="Tax amount in paise")
    billing_reason: str = Field(default="MANUAL_INVOICE", max_length=64)
    status: Literal["DRAFT", "OPEN", "PAID"] = "OPEN"


class InvoiceSummarySchema(BaseModel):
    total_invoiced_amount: int
    collected_paid_amount: int
    pending_open_amount: int
    uncollectible_amount: int
    total_count: int
    paid_count: int
    open_count: int
    draft_count: int
    uncollectible_count: int
    void_count: int
    collected_percentage: int
    growth_percentage: float

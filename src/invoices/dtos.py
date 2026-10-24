from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

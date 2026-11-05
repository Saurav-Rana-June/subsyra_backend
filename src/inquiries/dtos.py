from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime


class InquiryCreateSchema(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    company_name: Optional[str] = Field(default=None, max_length=255)
    monthly_volume: Optional[str] = Field(default=None, max_length=100)
    message: Optional[str] = Field(default=None, max_length=5000)


class InquiryUpdateStatusSchema(BaseModel):
    status: Literal["NEW", "CONTACTED", "QUALIFIED", "CLOSED"]


class InquiryReadSchema(BaseModel):
    id: int
    full_name: str
    email: str
    company_name: Optional[str] = None
    monthly_volume: Optional[str] = None
    message: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


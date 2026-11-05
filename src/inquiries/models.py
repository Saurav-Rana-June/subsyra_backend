from src.utils.db import Base
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime, timezone
from enum import Enum


class InquiryStatus(str, Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    CLOSED = "CLOSED"


class InquiryModel(Base):
    __tablename__ = "inquiries_table"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    company_name = Column(String(255), nullable=True)
    monthly_volume = Column(String(100), nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(50), default=InquiryStatus.NEW.value, nullable=False, index=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


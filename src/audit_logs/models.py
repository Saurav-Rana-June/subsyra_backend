from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from src.utils.db import Base
from src.users.models import UserModel


class AuditLogModel(Base):
    __tablename__ = "audit_logs_table"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users_table.id"), nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False, index=True)
    target_id = Column(Integer, nullable=True, index=True)
    details = Column(JSON, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    user = relationship("UserModel")

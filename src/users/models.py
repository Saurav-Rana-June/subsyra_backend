from src.utils.db import Base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from datetime import datetime, timezone
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"

class UserModel(Base):
    __tablename__ = "users_table"

    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    email_address = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    mobile_number = Column(String(10), nullable=False)
    profile_picture = Column(String, nullable=True)
    address = Column(String, nullable=True)
    role = Column(String, default=UserRole.CUSTOMER.value, server_default=UserRole.CUSTOMER.value, nullable=False)


class RevokedTokenModel(Base):
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False, index=True)
    revoked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DeletedUserModel(Base):
    __tablename__ = "delete_account_table"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    deleted_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
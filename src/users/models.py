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
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    email_address = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    country_code = Column(String(10), default="+91", server_default="+91", nullable=False)
    mobile_number = Column(String(20), nullable=False)
    profile_picture = Column(String, nullable=True)
    avatar_tone_index = Column(Integer, default=0, server_default="0", nullable=False)
    address = Column(String, nullable=True)
    role = Column(String, default=UserRole.CUSTOMER.value, server_default=UserRole.CUSTOMER.value, nullable=False)

    # Verification, 2FA, Token & Lifecycle state
    is_email_verified = Column(Boolean, default=True, server_default="true", nullable=False)
    pending_email = Column(String, nullable=True)
    two_factor_enabled = Column(Boolean, default=False, server_default="false", nullable=False)
    two_factor_secret = Column(String, nullable=True)
    token_version = Column(Integer, default=1, server_default="1", nullable=False)
    is_deleted = Column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    # Preferences & Localization
    pref_language = Column(String(16), default="en-US", server_default="en-US", nullable=False)
    pref_timezone = Column(String(32), default="IST", server_default="IST", nullable=False)
    pref_date_format = Column(String(20), default="DD.MM.YYYY", server_default="DD.MM.YYYY", nullable=False)
    pref_theme = Column(String(16), default="system", server_default="system", nullable=False)

    # Personal Notification Settings
    notif_security_alerts = Column(Boolean, default=True, server_default="true", nullable=False)
    notif_billing_summaries = Column(Boolean, default=True, server_default="true", nullable=False)
    notif_payment_failures = Column(Boolean, default=True, server_default="true", nullable=False)
    notif_product_updates = Column(Boolean, default=False, server_default="false", nullable=False)
    notif_billing_frequency = Column(String(16), default="weekly", server_default="weekly", nullable=False)


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


class UserSessionModel(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users_table.id", ondelete="CASCADE"), nullable=False, index=True)
    jti = Column(String(64), unique=True, nullable=False, index=True)
    device = Column(String(160), nullable=False, default="Web Browser")
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(64), nullable=True)
    location = Column(String(160), nullable=False, default="Unknown location")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_active_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class UserRecoveryCodeModel(Base):
    __tablename__ = "user_recovery_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users_table.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(128), nullable=False)
    code_hint = Column(String(32), nullable=False)
    is_used = Column(Boolean, default=False, server_default="false", nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class EmailVerificationTokenModel(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users_table.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, nullable=False)
    token = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
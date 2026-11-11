import json
import os
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from src.audit_logs.models import AuditLogModel
from src.audit_logs.services import record_audit_log
from src.users.dtos import (
    ChangePasswordSchema,
    EmailVerificationConfirmSchema,
    LoginTwoFactorSchema,
    TwoFactorDisableSchema,
    TwoFactorEnableSchema,
    UserCreateSchema,
    UserDeleteSchema,
    UserLoginSchema,
    UserNotificationsSchema,
    UserNotificationsUpdateSchema,
    UserPreferencesSchema,
    UserPreferencesUpdateSchema,
    UserReadSchema,
    UserSessionReadSchema,
    UserUpdateSchema,
)
from src.users.models import (
    DeletedUserModel,
    EmailVerificationTokenModel,
    RevokedTokenModel,
    UserModel,
    UserRecoveryCodeModel,
    UserRole,
    UserSessionModel,
)
from src.utils.helpers import (
    extract_token,
    generate_access_token,
    get_hashed_password,
    verify_password,
)
from src.utils.redis_cache import redis_cache
from src.utils.responses import ApiResponse
from src.utils.settings import settings
from src.utils.totp import (
    build_otpauth_uri,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    mask_recovery_code,
    verify_totp_code,
)

UPLOAD_DIR = "uploads/profile_pictures"
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_AVATAR_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MFA_CHALLENGE_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Internal Helpers (DRY serialization, session tracking, updates)
# ---------------------------------------------------------------------------
def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _split_full_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _serialize_preferences(user: UserModel) -> Dict[str, Any]:
    return UserPreferencesSchema(
        language=user.pref_language or "en-US",
        timezone=user.pref_timezone or "IST",
        date_format=user.pref_date_format or "DD.MM.YYYY",
        theme=user.pref_theme or "system",
    ).model_dump()


def _serialize_notifications(user: UserModel) -> Dict[str, Any]:
    return UserNotificationsSchema(
        security_alerts=True if user.notif_security_alerts is None else user.notif_security_alerts,
        billing_summaries=True if user.notif_billing_summaries is None else user.notif_billing_summaries,
        payment_failures=True if user.notif_payment_failures is None else user.notif_payment_failures,
        product_updates=False if user.notif_product_updates is None else user.notif_product_updates,
        billing_frequency=user.notif_billing_frequency or "weekly",
    ).model_dump()


def serialize_user(user: UserModel) -> Dict[str, Any]:
    fallback_first, fallback_last = _split_full_name(user.full_name)
    default_title = "Platform Admin" if user.role == UserRole.ADMIN.value else "Subscriber"
    schema = UserReadSchema(
        id=user.id,
        full_name=user.full_name,
        first_name=user.first_name if user.first_name is not None else fallback_first,
        last_name=user.last_name if user.last_name is not None else fallback_last,
        display_name=user.display_name or user.full_name,
        job_title=user.job_title or default_title,
        email_address=user.email_address,
        country_code=user.country_code or "+91",
        mobile_number=user.mobile_number,
        profile_picture=user.profile_picture,
        avatar_tone_index=user.avatar_tone_index or 0,
        address=user.address,
        role=user.role,
        is_email_verified=True if user.is_email_verified is None else user.is_email_verified,
        pending_email=user.pending_email,
        two_factor_enabled=bool(user.two_factor_enabled),
        preferences=_serialize_preferences(user),
        notifications=_serialize_notifications(user),
    )
    return schema.model_dump()


def _parse_device_name(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if not ua:
        return "Web Browser"

    browser = "Browser"
    if "subsyra" in ua or "dart" in ua:
        browser = "Subsyra App"
    elif "edg" in ua:
        browser = "Edge"
    elif "chrome" in ua and "chromium" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    elif "httpx" in ua or "testclient" in ua or "python" in ua:
        browser = "API Client"

    os_name = "Unknown OS"
    if "windows" in ua:
        os_name = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_name = "iOS"
    elif "android" in ua:
        os_name = "Android"
    elif "linux" in ua:
        os_name = "Linux"
    elif browser == "API Client":
        return "API Test Client"

    return f"{browser} on {os_name}"


def _extract_client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def _format_relative_time(dt: datetime, is_current: bool) -> str:
    if is_current:
        return "Active now"
    now = _utc_now_naive()
    target = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
    diff_sec = max(0, int((now - target).total_seconds()))
    if diff_sec < 120:
        return "Active now"
    if diff_sec < 3600:
        mins = diff_sec // 60
        return f"{mins} min ago" if mins == 1 else f"{mins} mins ago"
    if diff_sec < 86400:
        hours = diff_sec // 3600
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = diff_sec // 86400
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


def _create_user_session(
    db: Session,
    user: UserModel,
    request: Optional[Request] = None,
) -> tuple[str, UserSessionModel]:
    jti = str(uuid.uuid4())
    user_agent = request.headers.get("user-agent", "") if request else ""
    ip_address = _extract_client_ip(request)
    location_header = request.headers.get("x-client-location") if request else None
    location = location_header.strip() if location_header else f"{ip_address} · Direct"
    now = _utc_now_naive()
    expires_at = now + timedelta(minutes=settings.TOKEN_EXP_TIME)

    session_row = UserSessionModel(
        user_id=user.id,
        jti=jti,
        device=_parse_device_name(user_agent),
        user_agent=user_agent[:512] if user_agent else None,
        ip_address=ip_address[:64],
        location=location[:160],
        created_at=now,
        last_active_at=now,
        expires_at=expires_at,
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)

    token = generate_access_token(
        user.id,
        user.email_address,
        user.mobile_number,
        jti=jti,
        token_version=user.token_version or 1,
    )
    return token, session_row


def _revoke_sessions_for_user(
    db: Session,
    user_id: int,
    exclude_jti: Optional[str] = None,
) -> int:
    query = db.query(UserSessionModel).filter(
        UserSessionModel.user_id == user_id,
        UserSessionModel.revoked_at.is_(None),
    )
    if exclude_jti:
        query = query.filter(UserSessionModel.jti != exclude_jti)
    sessions = query.all()
    now = _utc_now_naive()
    for sess in sessions:
        sess.revoked_at = now
    return len(sessions)


def _create_verification_token(db: Session, user_id: int, email: str) -> EmailVerificationTokenModel:
    # Invalidate prior unused tokens for this user
    now = _utc_now_naive()
    db.query(EmailVerificationTokenModel).filter(
        EmailVerificationTokenModel.user_id == user_id,
        EmailVerificationTokenModel.verified_at.is_(None),
    ).delete(synchronize_session=False)

    token_value = secrets.token_urlsafe(32)
    record = EmailVerificationTokenModel(
        user_id=user_id,
        email=email,
        token=token_value,
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _apply_preferences_update(user: UserModel, prefs: UserPreferencesUpdateSchema) -> None:
    if prefs.language is not None:
        user.pref_language = prefs.language
    if prefs.timezone is not None:
        user.pref_timezone = prefs.timezone
    if prefs.date_format is not None:
        user.pref_date_format = prefs.date_format
    if prefs.theme is not None:
        user.pref_theme = prefs.theme


def _apply_notifications_update(user: UserModel, notif: UserNotificationsUpdateSchema) -> None:
    if notif.security_alerts is not None:
        user.notif_security_alerts = notif.security_alerts
    if notif.billing_summaries is not None:
        user.notif_billing_summaries = notif.billing_summaries
    if notif.payment_failures is not None:
        user.notif_payment_failures = notif.payment_failures
    if notif.product_updates is not None:
        user.notif_product_updates = notif.product_updates
    if notif.billing_frequency is not None:
        user.notif_billing_frequency = notif.billing_frequency


def _remove_stored_avatar_file(profile_picture: Optional[str]) -> None:
    if not profile_picture:
        return
    disk_path = profile_picture.lstrip("/")
    if os.path.exists(disk_path):
        try:
            os.remove(disk_path)
        except OSError:
            pass


def _replace_recovery_codes(db: Session, user_id: int) -> List[str]:
    db.query(UserRecoveryCodeModel).filter(
        UserRecoveryCodeModel.user_id == user_id
    ).delete(synchronize_session=False)

    plaintext_codes = generate_recovery_codes(6)
    now = _utc_now_naive()
    for code in plaintext_codes:
        db.add(
            UserRecoveryCodeModel(
                user_id=user_id,
                code_hash=hash_recovery_code(code),
                code_hint=mask_recovery_code(code),
                is_used=False,
                created_at=now,
            )
        )
    return plaintext_codes


# ---------------------------------------------------------------------------
# Auth & Core Profile Controllers
# ---------------------------------------------------------------------------
def register_user(body: UserCreateSchema, db: Session, request: Optional[Request] = None):
    user_with_email_address = db.query(UserModel).filter(
        UserModel.email_address == body.email_address,
        UserModel.is_deleted.is_(False),
    ).first()
    if user_with_email_address:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Email address already exists."
        )

    user_with_mobile_number = db.query(UserModel).filter(
        UserModel.mobile_number == body.mobile_number,
        UserModel.is_deleted.is_(False),
    ).first()
    if user_with_mobile_number:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Mobile number already exists."
        )

    first_name, last_name = _split_full_name(body.full_name)
    hashed_password = get_hashed_password(body.password)

    new_user = UserModel(
        full_name=body.full_name.strip(),
        first_name=first_name,
        last_name=last_name,
        display_name=body.full_name.strip(),
        email_address=body.email_address.strip(),
        hashed_password=hashed_password,
        mobile_number=body.mobile_number.strip(),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token, session_row = _create_user_session(db, new_user, request)

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="User registered successfully!",
        data={
            "token": token,
            "session_id": session_row.id,
            "user": serialize_user(new_user),
        }
    )


def login_user(body: UserLoginSchema, db: Session, request: Optional[Request] = None):
    user = db.query(UserModel).filter(
        UserModel.email_address == body.email_address,
        UserModel.is_deleted.is_(False),
    ).first()

    if not user:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Email does not exist. Please check!"
        )

    if not verify_password(body.password, user.hashed_password):
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Password is not correct. Please check!"
        )

    # If 2FA is active and secret configured, issue short-lived challenge token
    if user.two_factor_enabled and user.two_factor_secret:
        challenge_token = secrets.token_urlsafe(32)
        redis_cache.set(
            f"mfa_challenge:{challenge_token}",
            {"user_id": user.id},
            ttl=MFA_CHALLENGE_TTL_SECONDS,
        )
        return ApiResponse(
            status=status.HTTP_200_OK,
            message="Two-factor authentication required.",
            data={
                "requires_2fa": True,
                "challenge_token": challenge_token,
            }
        )

    token, session_row = _create_user_session(db, user, request)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User logged in successfully!",
        data={
            "token": token,
            "session_id": session_row.id,
            "user": serialize_user(user),
        }
    )


def verify_login_two_factor(body: LoginTwoFactorSchema, db: Session, request: Optional[Request] = None):
    challenge_data = redis_cache.get(f"mfa_challenge:{body.challenge_token}")
    if not challenge_data or not challenge_data.get("user_id"):
        return ApiResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Two-factor challenge expired or invalid."
        )

    user = db.query(UserModel).filter(
        UserModel.id == challenge_data["user_id"],
        UserModel.is_deleted.is_(False),
    ).first()
    if not user or not user.two_factor_enabled or not user.two_factor_secret:
        return ApiResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Invalid two-factor authentication state."
        )

    verified = verify_totp_code(user.two_factor_secret, body.code)
    if not verified:
        # Check one-time recovery codes
        candidate_hash = hash_recovery_code(body.code)
        recovery_row = db.query(UserRecoveryCodeModel).filter(
            UserRecoveryCodeModel.user_id == user.id,
            UserRecoveryCodeModel.code_hash == candidate_hash,
            UserRecoveryCodeModel.is_used.is_(False),
        ).first()
        if not recovery_row:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Invalid verification or recovery code."
            )
        recovery_row.is_used = True
        recovery_row.used_at = _utc_now_naive()
        db.commit()

    redis_cache.delete(f"mfa_challenge:{body.challenge_token}")
    token, session_row = _create_user_session(db, user, request)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User logged in successfully!",
        data={
            "token": token,
            "session_id": session_row.id,
            "user": serialize_user(user),
        }
    )


def logout_user(request: Request, db: Session):
    token = extract_token(request)
    if isinstance(token, ApiResponse):
        return token

    if token:
        redis_cache.revoke_token(token, exp_seconds=settings.TOKEN_EXP_TIME * 60)
        existing = db.query(RevokedTokenModel).filter(
            RevokedTokenModel.token == token
        ).first()
        if not existing:
            db.add(RevokedTokenModel(token=token))

    current_jti = getattr(request.state, "auth_jti", None)
    if current_jti:
        session_row = db.query(UserSessionModel).filter(
            UserSessionModel.jti == current_jti,
            UserSessionModel.revoked_at.is_(None),
        ).first()
        if session_row:
            session_row.revoked_at = _utc_now_naive()

    db.commit()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User logged out successfully"
    )


def get_user_profile(user: UserModel):
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User profile details fetched successfully",
        data=serialize_user(user),
    )


def update_user_profile(body: UserUpdateSchema, db: Session, user: UserModel):
    email_verification_sent = False

    # Name synchronization: supports first/last name fields or legacy full_name
    if body.first_name is not None:
        first_clean = body.first_name.strip()
        if not first_clean:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="First name cannot be empty."
            )
        user.first_name = first_clean
    if body.last_name is not None:
        user.last_name = body.last_name.strip()

    if body.full_name is not None:
        full_clean = body.full_name.strip()
        if not full_clean:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Fullname of user cannot be empty."
            )
        user.full_name = full_clean
        if body.first_name is None and body.last_name is None:
            f, l = _split_full_name(full_clean)
            user.first_name = f
            user.last_name = l
    elif body.first_name is not None or body.last_name is not None:
        combined = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if combined:
            user.full_name = combined

    if body.display_name is not None:
        display_clean = body.display_name.strip()
        if not display_clean:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Display name cannot be empty."
            )
        user.display_name = display_clean

    if body.job_title is not None:
        user.job_title = body.job_title.strip()

    if body.address is not None:
        user.address = body.address.strip()

    if body.avatar_tone_index is not None:
        user.avatar_tone_index = body.avatar_tone_index

    if body.country_code is not None:
        user.country_code = body.country_code

    if body.mobile_number is not None:
        mobile_clean = body.mobile_number.strip()
        if not mobile_clean or len(mobile_clean) > 20:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Valid mobile number (1-20 characters) is required."
            )
        duplicate_mobile = db.query(UserModel).filter(
            UserModel.mobile_number == mobile_clean,
            UserModel.id != user.id,
            UserModel.is_deleted.is_(False),
        ).first()
        if duplicate_mobile:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Mobile number is already in use by another account."
            )
        user.mobile_number = mobile_clean

    if body.email_address is not None:
        email_clean = body.email_address.strip().lower()
        if not email_clean or "@" not in email_clean:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="A valid email address is required."
            )
        duplicate_email = db.query(UserModel).filter(
            UserModel.email_address == email_clean,
            UserModel.id != user.id,
            UserModel.is_deleted.is_(False),
        ).first()
        if duplicate_email:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="Email address is already in use by another account."
            )
        if email_clean != user.email_address.lower():
            user.email_address = email_clean
            user.is_email_verified = False
            email_verification_sent = True

    if body.preferences is not None:
        _apply_preferences_update(user, body.preferences)

    if body.notifications is not None:
        _apply_notifications_update(user, body.notifications)

    db.commit()
    db.refresh(user)

    if email_verification_sent:
        _create_verification_token(db, user.id, user.email_address)

    record_audit_log(
        db=db,
        action="UPDATE_PROFILE",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
        details={"email_verification_sent": email_verification_sent},
    )

    msg = (
        f"Profile saved. Verification link sent to {user.email_address}."
        if email_verification_sent
        else "User profile details updated successfully"
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message=msg,
        data=serialize_user(user),
    )


# ---------------------------------------------------------------------------
# Avatar Upload & Removal Controllers
# ---------------------------------------------------------------------------
def upload_profile_picture(file: UploadFile, db: Session, user: UserModel):
    if file.content_type not in ALLOWED_AVATAR_MIME:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Unsupported image type. Allowed: PNG, JPEG, WEBP, GIF."
        )

    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0 or size > MAX_AVATAR_BYTES:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Image file must be between 1 byte and 5 MB."
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = ALLOWED_AVATAR_MIME[file.content_type]
    filename = f"user_{user.id}_{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, filename)

    _remove_stored_avatar_file(user.profile_picture)

    with open(dest_path, "wb") as out_file:
        shutil.copyfileobj(file.file, out_file)

    user.profile_picture = f"/{UPLOAD_DIR}/{filename}"
    db.commit()
    db.refresh(user)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Profile picture uploaded successfully.",
        data=serialize_user(user),
    )


def _remove_avatar_for_user(db: Session, target_user: UserModel):
    if not target_user.profile_picture and (target_user.avatar_tone_index or 0) == 0:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="User does not have a profile picture to delete."
        )

    _remove_stored_avatar_file(target_user.profile_picture)
    target_user.profile_picture = None
    target_user.avatar_tone_index = 0
    db.commit()
    db.refresh(target_user)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Profile picture deleted successfully.",
        data=serialize_user(target_user),
    )


def delete_own_profile_picture(db: Session, user: UserModel):
    return _remove_avatar_for_user(db, user)


def delete_profile_picture(id: int, db: Session, user: UserModel):
    if id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to modify another user's profile picture."
        )

    target_user = db.query(UserModel).filter(
        UserModel.id == id,
        UserModel.is_deleted.is_(False),
    ).first()
    if not target_user:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="User not found"
        )

    return _remove_avatar_for_user(db, target_user)


# ---------------------------------------------------------------------------
# Email Verification Controllers
# ---------------------------------------------------------------------------
def resend_email_verification(db: Session, user: UserModel):
    if user.is_email_verified:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Your email address is already verified."
        )

    token_row = _create_verification_token(db, user.id, user.email_address)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Verification link sent to {user.email_address}.",
        data={
            "email_address": user.email_address,
            "verification_token": token_row.token,
            "expires_at": token_row.expires_at.isoformat(),
        }
    )


def confirm_email_verification(body: EmailVerificationConfirmSchema, db: Session, user: UserModel):
    token_row = db.query(EmailVerificationTokenModel).filter(
        EmailVerificationTokenModel.token == body.token,
        EmailVerificationTokenModel.user_id == user.id,
        EmailVerificationTokenModel.verified_at.is_(None),
    ).first()

    if not token_row:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Invalid or already used verification token."
        )

    now = _utc_now_naive()
    expires_at = token_row.expires_at.replace(tzinfo=None) if token_row.expires_at.tzinfo else token_row.expires_at
    if expires_at < now:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Verification token has expired. Request a new one."
        )

    token_row.verified_at = now
    user.is_email_verified = True
    user.pending_email = None
    db.commit()
    db.refresh(user)

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Email address verified successfully.",
        data=serialize_user(user),
    )


# ---------------------------------------------------------------------------
# Security Controllers (Password & Two-Factor Authentication)
# ---------------------------------------------------------------------------
def change_password(body: ChangePasswordSchema, request: Request, db: Session, user: UserModel):
    if not body.current_password:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Enter your current password."
        )

    if not verify_password(body.current_password, user.hashed_password):
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Current password is incorrect."
        )

    if len(body.new_password) < 8:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="New password must be at least 8 characters."
        )

    if body.new_password == body.current_password:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="New password must differ from the current password."
        )

    if body.confirm_password is not None and body.new_password != body.confirm_password:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="New password and confirmation do not match."
        )

    user.hashed_password = get_hashed_password(body.new_password)
    current_jti = getattr(request.state, "auth_jti", None)
    revoked_others = _revoke_sessions_for_user(db, user.id, exclude_jti=current_jti)
    db.commit()

    record_audit_log(
        db=db,
        action="CHANGE_PASSWORD",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
        details={"revoked_other_sessions": revoked_others},
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Password updated successfully. Other devices must sign in again.",
        data={"revoked_sessions_count": revoked_others},
    )


def setup_two_factor(db: Session, user: UserModel):
    secret = generate_totp_secret()
    user.two_factor_secret = secret
    db.commit()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Two-factor setup initialized. Verify a code from your authenticator app to enable.",
        data={
            "secret": secret,
            "otpauth_url": build_otpauth_uri(secret, user.email_address),
        }
    )


def enable_two_factor(body: TwoFactorEnableSchema, db: Session, user: UserModel):
    secret = body.secret or user.two_factor_secret
    if not secret:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Initialize 2FA setup before verifying."
        )

    if not verify_totp_code(secret, body.code):
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Invalid 6-digit authenticator verification code."
        )

    user.two_factor_secret = secret
    user.two_factor_enabled = True
    recovery_codes = _replace_recovery_codes(db, user.id)
    db.commit()
    db.refresh(user)

    record_audit_log(
        db=db,
        action="ENABLE_2FA",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Two-factor authentication enabled.",
        data={
            "two_factor_enabled": True,
            "recovery_codes": recovery_codes,
        }
    )


def disable_two_factor(body: TwoFactorDisableSchema, db: Session, user: UserModel):
    if not user.two_factor_enabled:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Two-factor authentication is already disabled."
        )

    verified = False
    if body.password and verify_password(body.password, user.hashed_password):
        verified = True
    elif body.code and user.two_factor_secret and verify_totp_code(user.two_factor_secret, body.code):
        verified = True

    if not verified:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Provide your valid password or a current 2FA code to disable 2FA."
        )

    user.two_factor_enabled = False
    user.two_factor_secret = None
    db.query(UserRecoveryCodeModel).filter(
        UserRecoveryCodeModel.user_id == user.id
    ).delete(synchronize_session=False)
    db.commit()
    db.refresh(user)

    record_audit_log(
        db=db,
        action="DISABLE_2FA",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Two-factor authentication disabled.",
        data={"two_factor_enabled": False},
    )


def get_recovery_codes(db: Session, user: UserModel):
    rows = (
        db.query(UserRecoveryCodeModel)
        .filter(UserRecoveryCodeModel.user_id == user.id)
        .order_by(UserRecoveryCodeModel.id.asc())
        .all()
    )
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Recovery codes status fetched successfully.",
        data={
            "two_factor_enabled": bool(user.two_factor_enabled),
            "total_codes": len(rows),
            "remaining_codes": sum(1 for r in rows if not r.is_used),
            "codes": [
                {
                    "id": r.id,
                    "hint": r.code_hint,
                    "is_used": r.is_used,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    )


def regenerate_recovery_codes(db: Session, user: UserModel):
    if not user.two_factor_enabled:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Enable two-factor authentication before regenerating recovery codes."
        )

    new_codes = _replace_recovery_codes(db, user.id)
    db.commit()

    record_audit_log(
        db=db,
        action="REGENERATE_RECOVERY_CODES",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="New recovery codes generated. Previous codes have been invalidated.",
        data={"recovery_codes": new_codes},
    )


# ---------------------------------------------------------------------------
# Preferences & Notification Settings Controllers
# ---------------------------------------------------------------------------
def get_preferences(user: UserModel):
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Preferences fetched successfully.",
        data=_serialize_preferences(user),
    )


def update_preferences(body: UserPreferencesUpdateSchema, db: Session, user: UserModel):
    _apply_preferences_update(user, body)
    db.commit()
    db.refresh(user)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Preferences updated successfully.",
        data=_serialize_preferences(user),
    )


def get_notification_preferences(user: UserModel):
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Notification preferences fetched successfully.",
        data=_serialize_notifications(user),
    )


def update_notification_preferences(body: UserNotificationsUpdateSchema, db: Session, user: UserModel):
    _apply_notifications_update(user, body)
    db.commit()
    db.refresh(user)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Notification preferences updated successfully.",
        data=_serialize_notifications(user),
    )


# ---------------------------------------------------------------------------
# Sessions & Devices Controllers
# ---------------------------------------------------------------------------
def list_sessions(request: Request, db: Session, user: UserModel):
    current_jti = getattr(request.state, "auth_jti", None)
    now = _utc_now_naive()
    rows = (
        db.query(UserSessionModel)
        .filter(
            UserSessionModel.user_id == user.id,
            UserSessionModel.revoked_at.is_(None),
            UserSessionModel.expires_at > now,
        )
        .order_by(UserSessionModel.last_active_at.desc())
        .all()
    )

    serialized = [
        UserSessionReadSchema(
            id=row.id,
            device=row.device,
            ip_address=row.ip_address,
            location=row.location,
            last_active=_format_relative_time(row.last_active_at, row.jti == current_jti),
            last_active_at=row.last_active_at,
            created_at=row.created_at,
            is_current=(row.jti == current_jti),
        ).model_dump(mode="json")
        for row in rows
    ]
    serialized.sort(key=lambda item: (not item["is_current"],))

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Active sessions fetched successfully.",
        data={"sessions": serialized, "total": len(serialized)},
    )


def revoke_session(session_id: int, request: Request, db: Session, user: UserModel):
    current_jti = getattr(request.state, "auth_jti", None)
    session_row = db.query(UserSessionModel).filter(
        UserSessionModel.id == session_id,
        UserSessionModel.user_id == user.id,
        UserSessionModel.revoked_at.is_(None),
    ).first()

    if not session_row:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="Active session not found."
        )

    if session_row.jti == current_jti:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Use sign out to terminate your current session."
        )

    session_row.revoked_at = _utc_now_naive()
    db.commit()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"{session_row.device} was logged out.",
        data={"revoked_session_id": session_id},
    )


def revoke_other_sessions(request: Request, db: Session, user: UserModel):
    current_jti = getattr(request.state, "auth_jti", None)
    revoked_count = _revoke_sessions_for_user(db, user.id, exclude_jti=current_jti)
    db.commit()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Logged out of all other sessions.",
        data={"revoked_count": revoked_count},
    )


# ---------------------------------------------------------------------------
# Danger Zone Controllers (Personal Data Export & Account Deletion)
# ---------------------------------------------------------------------------
def export_personal_data(download: bool, db: Session, user: UserModel):
    sessions = (
        db.query(UserSessionModel)
        .filter(UserSessionModel.user_id == user.id)
        .order_by(UserSessionModel.created_at.desc())
        .all()
    )
    audit_events = (
        db.query(AuditLogModel)
        .filter(AuditLogModel.user_id == user.id)
        .order_by(AuditLogModel.created_at.desc())
        .limit(200)
        .all()
    )

    export_payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": serialize_user(user),
        "login_history": [
            {
                "id": s.id,
                "device": s.device,
                "ip_address": s.ip_address,
                "location": s.location,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
                "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
            }
            for s in sessions
        ],
        "activity_history": [
            {
                "id": a.id,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "details": a.details,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audit_events
        ],
    }

    if download:
        return Response(
            content=json.dumps(export_payload, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="subsyra-personal-data-user-{user.id}.json"'
            },
        )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Personal data export ready.",
        data=export_payload,
    )


def delete_account(body: UserDeleteSchema, request: Request, db: Session, user: UserModel):
    if not body.password:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Enter your password to confirm."
        )

    if not verify_password(body.password, user.hashed_password):
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Incorrect password. Account deletion aborted."
        )

    now = _utc_now_naive()
    original_email = user.email_address

    db.add(
        DeletedUserModel(
            user_id=user.id,
            reason=body.reason or "User requested account deletion",
            deleted_at=now,
        )
    )

    _remove_stored_avatar_file(user.profile_picture)
    _revoke_sessions_for_user(db, user.id)

    db.query(UserRecoveryCodeModel).filter(
        UserRecoveryCodeModel.user_id == user.id
    ).delete(synchronize_session=False)
    db.query(EmailVerificationTokenModel).filter(
        EmailVerificationTokenModel.user_id == user.id
    ).delete(synchronize_session=False)

    token = extract_token(request)
    if not isinstance(token, ApiResponse) and token:
        redis_cache.revoke_token(token, exp_seconds=settings.TOKEN_EXP_TIME * 60)
        if not db.query(RevokedTokenModel).filter(RevokedTokenModel.token == token).first():
            db.add(RevokedTokenModel(token=token))

    # Preserve FK integrity for billing/subscriptions while liberating email/mobile
    user.is_deleted = True
    user.deleted_at = now
    user.token_version = (user.token_version or 1) + 1
    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.profile_picture = None
    user.email_address = f"deleted_{user.id}_{original_email}"
    user.mobile_number = f"del_{user.id}"[:20]
    db.commit()

    record_audit_log(
        db=db,
        action="DELETE_ACCOUNT",
        target_type="USER",
        target_id=user.id,
        user_id=user.id,
        details={"reason": body.reason or "User requested account deletion"},
    )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Deletion requested. Account permanently deactivated.",
    )

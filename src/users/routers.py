from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from src.users import controllers
from src.users.dtos import (
    ChangePasswordSchema,
    EmailVerificationConfirmSchema,
    LoginTwoFactorSchema,
    TwoFactorDisableSchema,
    TwoFactorEnableSchema,
    UserCreateSchema,
    UserDeleteSchema,
    UserLoginSchema,
    UserNotificationsUpdateSchema,
    UserPreferencesUpdateSchema,
    UserUpdateSchema,
)
from src.users.models import UserModel
from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.utils.responses import ApiResponse

user_routes = APIRouter(prefix="/users", tags=["User"])


@user_routes.post("/register", status_code=status.HTTP_200_OK)
def register_user(body: UserCreateSchema, request: Request, db: Session = Depends(get_db)):
    return controllers.register_user(body, db, request)


@user_routes.post("/login", status_code=status.HTTP_200_OK)
def login_user(body: UserLoginSchema, request: Request, db: Session = Depends(get_db)):
    return controllers.login_user(body, db, request)


@user_routes.post("/login/2fa", status_code=status.HTTP_200_OK)
def verify_login_two_factor(body: LoginTwoFactorSchema, request: Request, db: Session = Depends(get_db)):
    return controllers.verify_login_two_factor(body, db, request)


@user_routes.delete("/logout", status_code=status.HTTP_200_OK)
def logout_user(
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.logout_user(request, db)


@user_routes.get("/me", status_code=status.HTTP_200_OK)
def get_user_profile(user: UserModel = Depends(is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_user_profile(user)


@user_routes.put("/me", status_code=status.HTTP_200_OK)
@user_routes.patch("/me", status_code=status.HTTP_200_OK)
def update_user_profile(
    body: UserUpdateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_user_profile(body, db, user)


@user_routes.delete("/me", status_code=status.HTTP_200_OK)
def delete_own_account(
    body: UserDeleteSchema,
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.delete_account(body, request, db, user)


@user_routes.post("/me/delete", status_code=status.HTTP_200_OK)
def delete_own_account_post(
    body: UserDeleteSchema,
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.delete_account(body, request, db, user)


# ---------------------------------------------------------------------------
# Avatar / Profile Picture Routes
# ---------------------------------------------------------------------------
@user_routes.post("/me/profile-picture", status_code=status.HTTP_200_OK)
def upload_profile_picture(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.upload_profile_picture(file, db, user)


@user_routes.delete("/me/profile-picture", status_code=status.HTTP_200_OK)
def delete_own_profile_picture(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.delete_own_profile_picture(db, user)


@user_routes.delete("/profile_picture/{id}", status_code=status.HTTP_200_OK)
def delete_profile_picture(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.delete_profile_picture(id, db, user)


# ---------------------------------------------------------------------------
# Email Verification Routes
# ---------------------------------------------------------------------------
@user_routes.post("/me/email-verification/resend", status_code=status.HTTP_200_OK)
def resend_email_verification(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.resend_email_verification(db, user)


@user_routes.post("/me/email-verification/confirm", status_code=status.HTTP_200_OK)
def confirm_email_verification(
    body: EmailVerificationConfirmSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.confirm_email_verification(body, db, user)


# ---------------------------------------------------------------------------
# Security & 2FA Routes
# ---------------------------------------------------------------------------
@user_routes.post("/me/change-password", status_code=status.HTTP_200_OK)
def change_password(
    body: ChangePasswordSchema,
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.change_password(body, request, db, user)


@user_routes.post("/me/2fa/setup", status_code=status.HTTP_200_OK)
def setup_two_factor(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.setup_two_factor(db, user)


@user_routes.post("/me/2fa/enable", status_code=status.HTTP_200_OK)
def enable_two_factor(
    body: TwoFactorEnableSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.enable_two_factor(body, db, user)


@user_routes.post("/me/2fa/disable", status_code=status.HTTP_200_OK)
def disable_two_factor_post(
    body: TwoFactorDisableSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.disable_two_factor(body, db, user)


@user_routes.delete("/me/2fa", status_code=status.HTTP_200_OK)
def disable_two_factor_delete(
    body: TwoFactorDisableSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.disable_two_factor(body, db, user)


@user_routes.get("/me/2fa/recovery-codes", status_code=status.HTTP_200_OK)
def get_recovery_codes(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_recovery_codes(db, user)


@user_routes.post("/me/2fa/recovery-codes/regenerate", status_code=status.HTTP_200_OK)
def regenerate_recovery_codes(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.regenerate_recovery_codes(db, user)


# ---------------------------------------------------------------------------
# Preferences & Notifications Routes
# ---------------------------------------------------------------------------
@user_routes.get("/me/preferences", status_code=status.HTTP_200_OK)
def get_preferences(user: UserModel = Depends(is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_preferences(user)


@user_routes.put("/me/preferences", status_code=status.HTTP_200_OK)
def update_preferences(
    body: UserPreferencesUpdateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_preferences(body, db, user)


@user_routes.get("/me/notifications", status_code=status.HTTP_200_OK)
def get_notification_preferences(user: UserModel = Depends(is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_notification_preferences(user)


@user_routes.put("/me/notifications", status_code=status.HTTP_200_OK)
def update_notification_preferences(
    body: UserNotificationsUpdateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_notification_preferences(body, db, user)


# ---------------------------------------------------------------------------
# Active Sessions & Devices Routes
# ---------------------------------------------------------------------------
@user_routes.get("/me/sessions", status_code=status.HTTP_200_OK)
def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.list_sessions(request, db, user)


@user_routes.delete("/me/sessions/others", status_code=status.HTTP_200_OK)
@user_routes.delete("/me/sessions", status_code=status.HTTP_200_OK)
def revoke_other_sessions(
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.revoke_other_sessions(request, db, user)


@user_routes.delete("/me/sessions/{session_id}", status_code=status.HTTP_200_OK)
def revoke_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.revoke_session(session_id, request, db, user)


# ---------------------------------------------------------------------------
# Personal Data Export Route
# ---------------------------------------------------------------------------
@user_routes.get("/me/export", status_code=status.HTTP_200_OK)
def export_personal_data(
    download: bool = Query(default=False, description="Return raw JSON file attachment when true"),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.export_personal_data(download, db, user)

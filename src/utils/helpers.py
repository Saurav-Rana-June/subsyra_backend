from fastapi import HTTPException, Request, status, Depends
from pwdlib import PasswordHash
import calendar
import jwt
import hashlib
from typing import Any, Callable, Dict, Optional, Tuple
from src.utils import settings
from datetime import datetime, timedelta, timezone
from src.utils.responses import ApiResponse
from sqlalchemy.orm import Session
from src.utils.db import get_db
from src.users.models import UserModel, RevokedTokenModel, UserRole
from src.utils.settings import settings
from starlette.requests import Request
from starlette.responses import Response

password_hash = PasswordHash.recommended()


def get_hashed_password(password):
    return password_hash.hash(password)


def verify_password(plain_password, hashed_password):
    return password_hash.verify(plain_password, hashed_password)


def generate_access_token(id: int, email_address: str, mobile_number: str):
    exp_time = datetime.now(timezone.utc) + timedelta(
        minutes=settings.TOKEN_EXP_TIME
    )

    return jwt.encode({"_id": id, "emailAddress": email_address,
                       "mobileNumber": mobile_number, "exp": exp_time},  settings.SECRET_KEY, settings.ALGORITHM)


def extract_token(request: Request):
    authorization = request.headers.get("authorization")

    if not authorization:
        return ApiResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Authentication Token is required!"
        )

    if not authorization.startswith("Bearer "):
        return ApiResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Invalid authentication token!"
        )

    return authorization.split(" ", 1)[1]


def is_authenticated(request: Request, db: Session = Depends(get_db)):
    try:
        token = extract_token(request)

        revoked_token = db.query(RevokedTokenModel).filter(
            RevokedTokenModel.token == token).first()

        if revoked_token:
            return ApiResponse(
                status=status.HTTP_401_UNAUTHORIZED,
                message="Your token is expired! Please login again."
            )

        data = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        user_id = data.get("_id")

        if not user_id:
            return ApiResponse(
                status=status.HTTP_401_UNAUTHORIZED,
                message="Your token is invalid!"
            )

        user_data = db.query(UserModel).filter(UserModel.id == user_id).first()

        if not user_data:
            return ApiResponse(
                status=status.HTTP_401_UNAUTHORIZED,
                message="Your token is invalid!"
            )

        return user_data

    except:
        return ApiResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Your token is expired or invalid! Please login again."
        )


def custom_key_builder(
    func: Callable[..., Any],
    namespace: str = "",
    *,
    request: Optional[Request] = None,
    response: Optional[Response] = None,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> str:
    # Build key from request path and query parameters
    raw_key = f"{request.url.path}?{request.url.query}" if request else f"{func.__name__}:{kwargs}"
    cache_key = hashlib.md5(raw_key.encode()).hexdigest()
    return f"{namespace}:{func.__name__}:{cache_key}"


def require_roles(*allowed_roles: UserRole):
    def role_checker(user: UserModel = Depends(is_authenticated)):
        # 1. If authentication failed, return the 401 error
        if isinstance(user, ApiResponse):
            return user

        # 2. Extract string values from the permitted enums
        allowed_roles_values = [role.value for role in allowed_roles]

        # 3. Check if current user has permission
        if user.role not in allowed_roles_values:
            return ApiResponse(
                status=status.HTTP_403_FORBIDDEN,
                message="You do not have permission to access this resource!"
            )

        # 4. Return the authorized user
        return user

    return role_checker


def calculate_period_end(start_date: datetime, interval: str, count: int = 1) -> datetime:
    if interval == "year":
        try:
            return start_date.replace(year=start_date.year + count)
        except ValueError:
            return start_date.replace(year=start_date.year + count, day=28)

    elif interval == "month":
        total_months = start_date.month - 1 + count
        new_year = start_date.year + (total_months // 12)
        new_month = (total_months % 12) + 1
        max_days = calendar.monthrange(new_year, new_month)[1]
        new_day = min(start_date.day, max_days)
        return start_date.replace(year=new_year, month=new_month, day=new_day)

    elif interval == "week":
        return start_date + timedelta(weeks=count)

    elif interval == "day":
        return start_date + timedelta(days=count)

    # Fallback to 30 days
    return start_date + timedelta(days=30 * count)

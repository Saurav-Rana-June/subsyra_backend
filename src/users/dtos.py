from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
from src.users.models import UserRole

LanguageChoice = Literal["en-US", "en-GB", "hi"]
TimezoneChoice = Literal["IST", "UTC", "EST"]
DateFormatChoice = Literal["DD.MM.YYYY", "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"]
ThemeChoice = Literal["system", "light", "dark"]
BillingFrequencyChoice = Literal["daily", "weekly", "monthly"]


class UserCreateSchema(BaseModel):
    full_name: str
    email_address: str
    mobile_number: str
    password: str


class UserLoginSchema(BaseModel):
    email_address: str
    password: str


class LoginTwoFactorSchema(BaseModel):
    challenge_token: str
    code: str


class UserPreferencesSchema(BaseModel):
    language: LanguageChoice = "en-US"
    timezone: TimezoneChoice = "IST"
    date_format: DateFormatChoice = "DD.MM.YYYY"
    theme: ThemeChoice = "system"


class UserPreferencesUpdateSchema(BaseModel):
    language: Optional[LanguageChoice] = None
    timezone: Optional[TimezoneChoice] = None
    date_format: Optional[DateFormatChoice] = None
    theme: Optional[ThemeChoice] = None


class UserNotificationsSchema(BaseModel):
    security_alerts: bool = True
    billing_summaries: bool = True
    payment_failures: bool = True
    product_updates: bool = False
    billing_frequency: BillingFrequencyChoice = "weekly"


class UserNotificationsUpdateSchema(BaseModel):
    security_alerts: Optional[bool] = None
    billing_summaries: Optional[bool] = None
    payment_failures: Optional[bool] = None
    product_updates: Optional[bool] = None
    billing_frequency: Optional[BillingFrequencyChoice] = None


class UserReadSchema(BaseModel):
    id: int
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    job_title: Optional[str] = None
    email_address: str
    country_code: str = "+91"
    mobile_number: str
    profile_picture: Optional[str] = None
    avatar_tone_index: int = 0
    address: Optional[str] = None
    role: UserRole = UserRole.CUSTOMER
    is_email_verified: bool = True
    pending_email: Optional[str] = None
    two_factor_enabled: bool = False
    preferences: UserPreferencesSchema = Field(default_factory=UserPreferencesSchema)
    notifications: UserNotificationsSchema = Field(default_factory=UserNotificationsSchema)

    model_config = {
        "from_attributes": True
    }


class UserUpdateSchema(BaseModel):
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    job_title: Optional[str] = None
    email_address: Optional[str] = None
    country_code: Optional[str] = None
    mobile_number: Optional[str] = None
    address: Optional[str] = None
    avatar_tone_index: Optional[int] = Field(default=None, ge=0, le=20)
    preferences: Optional[UserPreferencesUpdateSchema] = None
    notifications: Optional[UserNotificationsUpdateSchema] = None

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip()
        if not cleaned.startswith("+") or len(cleaned) > 10:
            raise ValueError("Invalid country code format.")
        return cleaned

    model_config = {
        "from_attributes": True
    }


class ChangePasswordSchema(BaseModel):
    current_password: str
    new_password: str
    confirm_password: Optional[str] = None


class TwoFactorEnableSchema(BaseModel):
    code: str
    secret: Optional[str] = None


class TwoFactorDisableSchema(BaseModel):
    password: Optional[str] = None
    code: Optional[str] = None


class EmailVerificationConfirmSchema(BaseModel):
    token: str


class UserSessionReadSchema(BaseModel):
    id: int
    device: str
    ip_address: Optional[str] = None
    location: str
    last_active: str
    last_active_at: datetime
    created_at: datetime
    is_current: bool


class UserDeleteSchema(BaseModel):
    password: str
    reason: Optional[str] = "User requested account deletion"

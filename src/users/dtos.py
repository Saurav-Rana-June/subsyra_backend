from pydantic import BaseModel, Field
from typing import Optional
from src.users.models import UserRole


class UserCreateSchema(BaseModel):
    full_name: str
    email_address: str
    mobile_number: str
    password: str


class UserLoginSchema(BaseModel):
    email_address: str
    password: str


class UserReadSchema(BaseModel):
    id: int
    full_name: str
    email_address: str
    mobile_number: str
    profile_picture: Optional[str] = None
    address: Optional[str] = None
    role: UserRole = UserRole.CUSTOMER

    model_config = {
        "from_attributes": True
    }


class UserUpdateSchema(BaseModel):
    full_name: str
    email_address: str
    mobile_number: str
    address: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class UserDeleteSchema(BaseModel):
    reason: str

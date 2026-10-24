import os
import uuid
import shutil
from fastapi import UploadFile
from sqlalchemy.orm import Session
from fastapi import status, Request
from src.utils.responses import ApiResponse
from src.utils.helpers import get_hashed_password, generate_access_token, verify_password, extract_token
from src.users.models import UserModel, RevokedTokenModel, DeletedUserModel
from src.users.dtos import UserCreateSchema, UserLoginSchema, UserReadSchema, UserUpdateSchema, UserDeleteSchema

UPLOAD_DIR = "uploads/profile_pictures"


def register_user(body: UserCreateSchema, db: Session):
    user_with_email_address = db.query(UserModel).filter(
        UserModel.email_address == body.email_address).first()

    if user_with_email_address:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Email address already exists."
        )

    user_with_mobile_number = db.query(UserModel).filter(
        UserModel.mobile_number == body.mobile_number).first()

    if user_with_mobile_number:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Mobile number already exists."
        )

    hashed_password = get_hashed_password(body.password)

    new_user = UserModel(
        full_name=body.full_name,
        email_address=body.email_address,
        hashed_password=hashed_password,
        mobile_number=body.mobile_number,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    responseData = UserReadSchema.model_validate(new_user).model_dump()

    token = generate_access_token(
        new_user.id, new_user.email_address, new_user.mobile_number)

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="User registered successfully!",
        data={
            "token": token,
            "user": responseData
        }
    )


def login_user(body: UserLoginSchema, db: Session):
    user_with_email_address = db.query(UserModel).filter(
        UserModel.email_address == body.email_address).first()

    if not user_with_email_address:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Email does not exist. Please check!"
        )

    password_matches = verify_password(
        body.password, user_with_email_address.hashed_password)

    if not password_matches:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Password is not correct. Please check!"
        )

    token = generate_access_token(
        user_with_email_address.id, user_with_email_address.email_address, user_with_email_address.mobile_number)

    responseData = UserReadSchema.model_validate(
        user_with_email_address).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User logged in successfully!",
        data={
            "token": token,
            "user": responseData
        }
    )


def logout_user(request: Request, db: Session):
    token = extract_token(request)

    revoked_token = RevokedTokenModel(token=token)
    db.add(revoked_token)
    db.commit()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User logged out successfully"
    )


def get_user_profile(user: UserModel):
    responseData = UserReadSchema.model_validate(user).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User profile details fetched successfully",
        data=responseData
    )


def update_user_profile(body: UserUpdateSchema, db: Session, user: UserModel):
    if body.full_name is None:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Fullname of user cannot be empty.",
        )

    user.full_name = body.full_name

    if body.email_address is None:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Email address of user cannot be empty.",
        )

    user.email_address = body.email_address

    if body.mobile_number is None:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Mobile of user cannot be empty.",
        )

    user.mobile_number = body.mobile_number

    db.commit()
    db.refresh(user)

    responseData = UserReadSchema.model_validate(user).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="User profile details updated successfully",
        data=responseData
    )


def delete_profile_picture(id: int, db: Session, user: UserModel):
    # 1. Fetch the user
    user = db.query(UserModel).filter(UserModel.id == id).first()
    if not user:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="User not found"
        )

    # 2. Check if profile picture exists
    if not user.profile_picture:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="User does not have a profile picture to delete."
        )

    # 3. Remove picture from disk if it exists
    if os.path.exists(user.profile_picture):
        try:
            os.remove(user.profile_picture)
        except OSError:
            pass

    # 4. Set profile_picture field to None in DB
    user.profile_picture = None
    db.commit()
    db.refresh(user)

    responseData = UserReadSchema.model_validate(user).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Profile picture deleted successfully.",
        data=responseData
    )

from fastapi import APIRouter, Depends, status, Request, UploadFile, File
from src.utils.db import get_db
from sqlalchemy.orm import Session
from src.users import controllers
from src.users.dtos import UserCreateSchema, UserLoginSchema, UserUpdateSchema, UserDeleteSchema
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.utils.helpers import get_hashed_password, generate_access_token, verify_password, extract_token, is_authenticated

user_routes = APIRouter(prefix="/users", tags=["User"])


@user_routes.post("/register", status_code=status.HTTP_200_OK)
def register_user(body: UserCreateSchema, db: Session = Depends(get_db)):
    return controllers.register_user(body, db)


@user_routes.post("/login", status_code=status.HTTP_200_OK)
def login_user(body: UserLoginSchema, db: Session = Depends(get_db)):
    return controllers.login_user(body, db)


@user_routes.delete("/logout", status_code=status.HTTP_200_OK)
def logout_user(request: Request,  db: Session = Depends(get_db), user: UserModel = Depends(
        is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.logout_user(request, db)


@user_routes.get("/me", status_code=status.HTTP_200_OK)
def get_user_profile(user: UserModel = Depends(
        is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_user_profile(user)


@user_routes.put("/me", status_code=status.HTTP_200_OK)
def update_user_profile(body: UserUpdateSchema, db: Session = Depends(get_db), user: UserModel = Depends(
        is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_user_profile(body, db, user)


@user_routes.delete("/profile_picture/{id}", status_code=status.HTTP_200_OK)
def delete_profile_picture(id: int, db: Session = Depends(get_db), user: UserModel = Depends(is_authenticated)):
    if isinstance(user, ApiResponse):
        return user
    return controllers.delete_profile_picture(id, db, user)

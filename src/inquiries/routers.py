from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from src.utils.db import get_db
from src.inquiries import controllers
from src.inquiries.dtos import InquiryCreateSchema, InquiryUpdateStatusSchema
from src.utils.helpers import require_roles
from src.users.models import UserModel, UserRole
from src.utils.responses import ApiResponse

inquiry_routes = APIRouter(prefix="/inquiries", tags=["Enterprise Inquiries"])


@inquiry_routes.post("", status_code=status.HTTP_201_CREATED)
def submit_inquiry(
    body: InquiryCreateSchema,
    db: Session = Depends(get_db),
):
    return controllers.create_inquiry(body=body, db=db)


@inquiry_routes.get("", status_code=status.HTTP_200_OK)
def get_inquiries(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin
    return controllers.get_all_inquiries(db=db, status_filter=status_filter)


@inquiry_routes.patch("/{id}/status", status_code=status.HTTP_200_OK)
def update_inquiry_status(
    id: int,
    body: InquiryUpdateStatusSchema,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin
    return controllers.update_inquiry_status(id=id, body=body, db=db, admin=admin)


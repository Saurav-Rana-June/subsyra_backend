from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from src.utils.db import get_db
from src.utils.helpers import is_authenticated
from src.users.models import UserModel
from src.utils.responses import ApiResponse
from src.invoices import controllers

invoice_routes = APIRouter(prefix="/invoices", tags=["Invoices"])


@invoice_routes.get("", status_code=status.HTTP_200_OK)
def list_invoices(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_all_invoices(db=db, user=user)


@invoice_routes.get("/{id}", status_code=status.HTTP_200_OK)
def get_invoice(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_invoice_by_id(id=id, db=db, user=user)

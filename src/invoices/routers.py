from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.invoices import controllers
from src.invoices.dtos import InvoiceCreateSchema
from src.users.models import UserModel, UserRole
from src.utils.db import get_db
from src.utils.helpers import is_authenticated, require_roles
from src.utils.responses import ApiResponse

invoice_routes = APIRouter(prefix="/invoices", tags=["Invoices"])


@invoice_routes.get("", status_code=status.HTTP_200_OK)
def list_invoices(
    subscription_id: Optional[int] = Query(
        None, description="Filter invoices by subscription ID"
    ),
    invoice_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter invoices by status (PAID, OPEN, DRAFT, UNCOLLECTIBLE, VOID)",
    ),
    billing_reason: Optional[str] = Query(
        None,
        description="Filter by billing reason (SUBSCRIPTION_CREATE, SUBSCRIPTION_CYCLE, PLAN_UPGRADE, MANUAL_INVOICE)",
    ),
    search: Optional[str] = Query(
        None, description="Search by invoice number, customer name, or email"
    ),
    start_date: Optional[datetime] = Query(
        None, description="Filter invoices created on or after this ISO timestamp"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Filter invoices created on or before this ISO timestamp"
    ),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_all_invoices(
        db=db,
        user=user,
        subscription_id=subscription_id,
        invoice_status=invoice_status,
        billing_reason=billing_reason,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )


@invoice_routes.post("", status_code=status.HTTP_201_CREATED)
def create_manual_invoice(
    body: InvoiceCreateSchema,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin
    return controllers.create_manual_invoice(body=body, db=db, admin=admin)


@invoice_routes.get("/summary", status_code=status.HTTP_200_OK)
def get_invoice_summary(
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_invoice_summary(db=db, user=user)


@invoice_routes.get("/export", status_code=status.HTTP_200_OK)
def export_invoices(
    subscription_id: Optional[int] = Query(None),
    invoice_status: Optional[str] = Query(None, alias="status"),
    billing_reason: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.export_invoices_csv(
        db=db,
        user=user,
        subscription_id=subscription_id,
        invoice_status=invoice_status,
        billing_reason=billing_reason,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )


@invoice_routes.get("/{id}", status_code=status.HTTP_200_OK)
def get_invoice(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_invoice_by_id(id=id, db=db, user=user)


@invoice_routes.get("/{id}/receipt", status_code=status.HTTP_200_OK)
def get_invoice_receipt(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_invoice_receipt_html(id=id, db=db, user=user)


@invoice_routes.post("/{id}/mark-paid", status_code=status.HTTP_200_OK)
def mark_invoice_paid(
    id: int,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin
    return controllers.mark_invoice_paid(id=id, db=db, admin=admin)


@invoice_routes.post("/{id}/void", status_code=status.HTTP_200_OK)
def void_invoice(
    id: int,
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin
    return controllers.void_invoice(id=id, db=db, admin=admin)


@invoice_routes.post("/{id}/resend", status_code=status.HTTP_200_OK)
def resend_invoice_receipt(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.resend_invoice_receipt(id=id, db=db, user=user)

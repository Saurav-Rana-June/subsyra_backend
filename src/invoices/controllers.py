from sqlalchemy.orm import Session
from fastapi import status
from src.utils.responses import ApiResponse
from src.users.models import UserModel, UserRole
from src.invoices.models import InvoiceModel
from src.invoices.dtos import InvoiceReadSchema


def get_all_invoices(db: Session, user: UserModel):
    query = db.query(InvoiceModel)
    if user.role != UserRole.ADMIN.value:
        query = query.filter(InvoiceModel.user_id == user.id)

    invoices = query.order_by(InvoiceModel.id.desc()).all()
    responseData = [
        InvoiceReadSchema.model_validate(inv).model_dump() for inv in invoices
    ]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Invoices fetched successfully",
        data=responseData,
    )


def get_invoice_by_id(id: int, db: Session, user: UserModel):
    invoice = db.query(InvoiceModel).filter(InvoiceModel.id == id).first()

    if not invoice:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND, message="Invoice not found"
        )

    if invoice.user_id != user.id and user.role != UserRole.ADMIN.value:
        return ApiResponse(
            status=status.HTTP_403_FORBIDDEN,
            message="You do not have permission to view this invoice.",
        )

    data = InvoiceReadSchema.model_validate(invoice).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Invoice fetched successfully",
        data=data,
    )

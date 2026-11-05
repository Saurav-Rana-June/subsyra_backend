from sqlalchemy.orm import Session
from fastapi import status
from typing import Optional
from src.utils.responses import ApiResponse
from src.inquiries.models import InquiryModel, InquiryStatus
from src.inquiries.dtos import (
    InquiryCreateSchema,
    InquiryReadSchema,
    InquiryUpdateStatusSchema,
)
from src.users.models import UserModel
from src.audit_logs.services import record_audit_log


def create_inquiry(
    body: InquiryCreateSchema,
    db: Session,
    user: Optional[UserModel] = None,
):
    inquiry = InquiryModel(
        full_name=body.full_name,
        email=str(body.email),
        company_name=body.company_name,
        monthly_volume=body.monthly_volume,
        message=body.message,
        status=InquiryStatus.NEW.value,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)

    # Record audit log if auth user or system
    record_audit_log(
        db=db,
        action="CREATE_INQUIRY",
        target_type="INQUIRY",
        target_id=inquiry.id,
        user_id=user.id if user else None,
        details={
            "email": inquiry.email,
            "company_name": inquiry.company_name,
            "monthly_volume": inquiry.monthly_volume,
        },
    )

    response_data = InquiryReadSchema.model_validate(inquiry).model_dump()

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Inquiry submitted successfully. Our team will contact you shortly.",
        data=response_data,
    )


def get_all_inquiries(
    db: Session,
    status_filter: Optional[str] = None,
):
    query = db.query(InquiryModel)
    if status_filter:
        query = query.filter(InquiryModel.status == status_filter.upper())

    inquiries = query.order_by(InquiryModel.created_at.desc()).all()
    response_data = [
        InquiryReadSchema.model_validate(i).model_dump() for i in inquiries
    ]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Inquiries fetched successfully",
        data=response_data,
    )


def update_inquiry_status(
    id: int,
    body: InquiryUpdateStatusSchema,
    db: Session,
    admin: UserModel,
):
    inquiry = db.query(InquiryModel).filter(InquiryModel.id == id).first()
    if not inquiry:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="Inquiry not found",
        )

    old_status = inquiry.status
    inquiry.status = body.status
    db.commit()
    db.refresh(inquiry)

    record_audit_log(
        db=db,
        action="UPDATE_INQUIRY_STATUS",
        target_type="INQUIRY",
        target_id=inquiry.id,
        user_id=admin.id,
        details={"old_status": old_status, "new_status": body.status},
    )

    response_data = InquiryReadSchema.model_validate(inquiry).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Inquiry status updated to {body.status}",
        data=response_data,
    )


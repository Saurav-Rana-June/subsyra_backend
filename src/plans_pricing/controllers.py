from sqlalchemy.orm import Session
from fastapi import status
from src.utils.responses import ApiResponse
from src.plans_pricing.models import PlanPricingModel
from src.users.models import UserModel
from src.audit_logs.services import record_audit_log
from src.plans_pricing.dtos import (
    PlanPricingCreateSchema,
    PlanPricingReadSchema,
    PlanPricingUpdateSchema
)


def create_plan_pricing(body: PlanPricingCreateSchema, db: Session, user: UserModel = None):
    existing_plan = db.query(PlanPricingModel).filter(
        PlanPricingModel.name == body.name
    ).first()

    if existing_plan:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="A plan with this name already exists."
        )

    new_plan_pricing = PlanPricingModel(**body.model_dump())
    db.add(new_plan_pricing)

    # Record plan creation in audit log
    record_audit_log(
        db=db,
        action="CREATE_PLAN",
        target_type="PLAN",
        target_id=new_plan_pricing.id,
        user_id=user.id if user else None,
        details={"name": new_plan_pricing.name, "price_amount": new_plan_pricing.price_amount},
    )

    db.commit()
    db.refresh(new_plan_pricing)

    responseData = PlanPricingReadSchema.model_validate(
        new_plan_pricing).model_dump()

    return ApiResponse(
        status=status.HTTP_201_CREATED,
        message="Plan created successfully",
        data=responseData
    )


def get_active_plans_pricings(db: Session):
    plans = db.query(PlanPricingModel).filter(
        PlanPricingModel.is_active == True
    ).all()

    responseData = [PlanPricingReadSchema.model_validate(
        p).model_dump() for p in plans]

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Active plans fetched successfully",
        data=responseData
    )


def get_plan_pricing_by_id(id: int, db: Session):
    plan = db.query(PlanPricingModel).filter(PlanPricingModel.id == id).first()

    if not plan:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="Plan not found",)

    responseData = PlanPricingReadSchema.model_validate(plan).model_dump()

    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Plan with id: {id} fetched successfully",
        data=responseData
    )


def update_plan_pricing(id: int, body: PlanPricingUpdateSchema, db: Session, user: UserModel = None):
    plan = db.query(PlanPricingModel).filter(PlanPricingModel.id == id).first()

    if not plan:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="Plan not found",)

    if body.name is not None:
        existing = db.query(PlanPricingModel).filter(
            PlanPricingModel.name == body.name,  PlanPricingModel.id != id).first()

        if existing:
            return ApiResponse(
                status=status.HTTP_400_BAD_REQUEST,
                message="A plan with this name already exists."
            )

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    # Record plan update in audit log
    record_audit_log(
        db=db,
        action="UPDATE_PLAN",
        target_type="PLAN",
        target_id=plan.id,
        user_id=user.id if user else None,
        details={"updated_fields": list(update_data.keys())},
    )

    db.commit()
    db.refresh(plan)

    responseData = PlanPricingReadSchema.model_validate(plan).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Plan updated successfully",
        data=responseData
    )


def archive_plan_pricing(id: int, db: Session, user: UserModel = None):
    plan = db.query(PlanPricingModel).filter(PlanPricingModel.id == id).first()

    if not plan:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message="Plan not found"
        )

    if not plan.is_active:
        return ApiResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="Plan is already archived."
        )

    plan.is_active = False

    # Record plan archive in audit log
    record_audit_log(
        db=db,
        action="ARCHIVE_PLAN",
        target_type="PLAN",
        target_id=plan.id,
        user_id=user.id if user else None,
        details={"name": plan.name},
    )

    db.commit()
    db.refresh(plan)

    responseData = PlanPricingReadSchema.model_validate(plan).model_dump()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Plan archived successfully",
        data=responseData
    )

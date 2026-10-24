from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from src.utils.db import get_db
from src.plans_pricing import controllers
from src.plans_pricing.dtos import PlanPricingCreateSchema, PlanPricingUpdateSchema
from src.utils.helpers import is_authenticated, require_roles
from src.users.models import UserModel, UserRole
from src.utils.responses import ApiResponse


plan_pricing_routes = APIRouter(prefix="/plans", tags=["Plans & Pricing"])


@plan_pricing_routes.get("", status_code=status.HTTP_200_OK)
def get_active_plans_pricings(db: Session = Depends(get_db)):
    return controllers.get_active_plans_pricings(db)


@plan_pricing_routes.get("/{id}", status_code=status.HTTP_200_OK)
def get_plan_pricing_by_id(id: int, db: Session = Depends(get_db)):
    return controllers.get_plan_pricing_by_id(id, db)


@plan_pricing_routes.post("", status_code=status.HTTP_201_CREATED)
def create_plan_pricing(
    body: PlanPricingCreateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_roles(UserRole.ADMIN))
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.create_plan_pricing(body, db, user=user)


@plan_pricing_routes.patch("/{id}", status_code=status.HTTP_200_OK)
def update_plan_pricing(
    id: int,
    body: PlanPricingUpdateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_roles(UserRole.ADMIN))
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_plan_pricing(id, body, db, user=user)


@plan_pricing_routes.patch("/{id}/archive", status_code=status.HTTP_200_OK)
def archive_plan_pricing(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_roles(UserRole.ADMIN))
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.archive_plan_pricing(id, db, user=user)
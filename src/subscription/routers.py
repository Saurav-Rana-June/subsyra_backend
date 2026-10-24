from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from src.utils.db import get_db
from src.utils.helpers import is_authenticated, require_roles
from src.users.models import UserModel
from src.subscription import controllers
from src.subscription.dtos import (
    SubscriptionStatus,
    SubscriptionCreateSchema,
    SubscriptionReadSchema,
    PlanChangeRequestSchema,
)
from src.utils.responses import ApiResponse
from src.utils.helpers import require_roles
from src.users.models import UserRole
from src.utils.subscription_services import process_subscription_renewals

subscription_routes = APIRouter(prefix="/subscription", tags=["Subscriptions"])


@subscription_routes.post("", status_code=status.HTTP_201_CREATED)
def create_subscription(
    body: SubscriptionCreateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.create_subscription(body=body, db=db, user=user)


@subscription_routes.get("", status_code=status.HTTP_200_OK)
def get_my_subscriptions(
    db: Session = Depends(get_db), user: UserModel = Depends(is_authenticated)
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_my_subscriptions(db=db, user=user)


@subscription_routes.get("/{id}", status_code=status.HTTP_200_OK)
def get_subscription_by_id(
    id: int, db: Session = Depends(get_db), user: UserModel = Depends(is_authenticated)
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_subscription_by_id(id=id, db=db, user=user)


@subscription_routes.post("/{id}/cancel", status_code=status.HTTP_200_OK)
def cancel_subscription(
    id: int, db: Session = Depends(get_db), user: UserModel = Depends(is_authenticated)
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.cancel_subscription(id=id, db=db, user=user)


@subscription_routes.post("/process-renewals", status_code=status.HTTP_200_OK)
def trigger_renewals(
    db: Session = Depends(get_db),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    if isinstance(admin, ApiResponse):
        return admin

    result = process_subscription_renewals(db=db)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Subscription renewals processed successfully",
        data=result,
    )


@subscription_routes.get("/{id}/preview-change", status_code=status.HTTP_200_OK)
def preview_change(
    id: int,
    new_plan_id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.preview_plan_change(
        id=id, new_plan_id=new_plan_id, db=db, user=user
    )


@subscription_routes.post("/{id}/change-plan", status_code=status.HTTP_200_OK)
def change_plan(
    id: int,
    body: PlanChangeRequestSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.execute_plan_change(id=id, body=body, db=db, user=user)

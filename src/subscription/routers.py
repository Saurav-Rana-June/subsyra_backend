from typing import Optional
from fastapi import APIRouter, Depends, Query, status
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
    PaymentMethodUpdateSchema,
)
from src.utils.responses import ApiResponse
from src.utils.helpers import require_roles
from src.users.models import UserRole
from src.utils.subscription_services import process_subscription_renewals
from src.utils.redis_cache import cache_response, TTL_SUBSCRIPTIONS

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
@cache_response(ttl=TTL_SUBSCRIPTIONS, prefix="subscription", user_scoped=True)
def get_my_subscriptions(
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE, TRIALING, PAST_DUE, PAUSED, CANCELLED, EXPIRED)"),
    user_id: Optional[int] = Query(None, description="Filter by customer / user ID (Admin only)"),
    search: Optional[str] = Query(None, description="Search by plan name, customer name, or customer email"),
    all_users: Optional[bool] = Query(False, description="When true, allows admin to fetch subscriptions across all customers"),
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_my_subscriptions(
        db=db,
        user=user,
        sub_status=status,
        user_id=user_id,
        search=search,
        all_users=all_users,
    )


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


@subscription_routes.post("/{id}/pause", status_code=status.HTTP_200_OK)
def pause_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.pause_subscription(id=id, db=db, user=user)


@subscription_routes.post("/{id}/resume", status_code=status.HTTP_200_OK)
def resume_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.resume_subscription(id=id, db=db, user=user)


@subscription_routes.post("/{id}/cancel-downgrade", status_code=status.HTTP_200_OK)
def cancel_downgrade(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.cancel_downgrade(id=id, db=db, user=user)


@subscription_routes.post("/{id}/reactivate", status_code=status.HTTP_200_OK)
def reactivate_subscription(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.reactivate_subscription(id=id, db=db, user=user)


@subscription_routes.get("/{id}/details", status_code=status.HTTP_200_OK)
@cache_response(ttl=TTL_SUBSCRIPTIONS, prefix="subscription", user_scoped=True)
def get_subscription_details(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_subscription_details(id=id, db=db, user=user)


@subscription_routes.get("/{id}/activity", status_code=status.HTTP_200_OK)
def get_subscription_activity(
    id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.get_subscription_activity(id=id, db=db, user=user)


@subscription_routes.post("/{id}/payment-method", status_code=status.HTTP_200_OK)
def update_subscription_payment_method(
    id: int,
    body: PaymentMethodUpdateSchema,
    db: Session = Depends(get_db),
    user: UserModel = Depends(is_authenticated),
):
    if isinstance(user, ApiResponse):
        return user
    return controllers.update_subscription_payment_method(
        id=id, body=body, db=db, user=user
    )

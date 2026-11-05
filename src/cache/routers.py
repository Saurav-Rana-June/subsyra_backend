from fastapi import APIRouter, Depends, Query, status
from typing import Optional
from src.utils.redis_cache import redis_cache
from src.utils.responses import ApiResponse
from src.utils.helpers import require_roles
from src.users.models import UserModel, UserRole

cache_routes = APIRouter(prefix="/cache", tags=["Cache & TTL Management"])


@cache_routes.get("/status", status_code=status.HTTP_200_OK)
def get_cache_status(
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    """Returns Redis connection state, total cached keys, and their remaining TTLs."""
    if isinstance(admin, ApiResponse):
        return admin

    stats = redis_cache.get_stats()
    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Cache status and TTL telemetry retrieved successfully",
        data=stats,
    )


@cache_routes.get("/keys", status_code=status.HTTP_200_OK)
def list_cached_keys(
    pattern: str = Query("*", description="Wildcard key pattern to inspect"),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    """Lists all active cached keys with their remaining Time-To-Live (TTL) in seconds."""
    if isinstance(admin, ApiResponse):
        return admin

    keys = redis_cache.get_all_active_keys(pattern)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Found {len(keys)} cached keys matching '{pattern}'",
        data=keys,
    )


@cache_routes.get("/keys/{key:path}", status_code=status.HTTP_200_OK)
def inspect_cached_key(
    key: str,
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    """Inspects the exact cached payload and remaining TTL for a specific key."""
    if isinstance(admin, ApiResponse):
        return admin

    data = redis_cache.get(key)
    ttl = redis_cache.get_ttl(key)

    if data is None and ttl == -2:
        return ApiResponse(
            status=status.HTTP_404_NOT_FOUND,
            message=f"Key '{key}' not found or already terminated by TTL.",
        )

    return ApiResponse(
        status=status.HTTP_200_OK,
        message="Key inspection retrieved successfully",
        data={
            "key": key,
            "ttl_seconds_remaining": ttl,
            "is_expired": ttl == -2,
            "payload": data,
        },
    )


@cache_routes.delete("/keys", status_code=status.HTTP_200_OK)
def purge_cached_keys(
    pattern: str = Query("*", description="Key pattern to purge (e.g. 'plans:*', 'dashboard:*', '*')"),
    admin: UserModel = Depends(require_roles(UserRole.ADMIN)),
):
    """Purges/terminates all cached keys matching the specified pattern."""
    if isinstance(admin, ApiResponse):
        return admin

    deleted_count = redis_cache.delete_pattern(pattern)
    return ApiResponse(
        status=status.HTTP_200_OK,
        message=f"Purged {deleted_count} cached keys matching '{pattern}' successfully.",
        data={"deleted_count": deleted_count, "pattern": pattern},
    )


import json
import logging
import inspect
from datetime import datetime, date
from functools import wraps
from typing import Any, Callable, Dict, List, Optional
from src.utils.settings import settings

try:
    import redis
except ImportError:
    redis = None

try:
    import fakeredis
except ImportError:
    fakeredis = None

logger = logging.getLogger("subsyra.cache")

# Standard TTL Presets (in seconds)
TTL_PLANS = 300          # 5 minutes for pricing tiers catalog
TTL_DASHBOARD = 60       # 1 minute for executive/customer dashboard KPIs
TTL_ANALYTICS = 300      # 5 minutes for reports, revenue trends, churn
TTL_SUBSCRIPTIONS = 120  # 2 minutes for user subscription lists
TTL_INQUIRIES = 180      # 3 minutes for enterprise inquiries list


class CacheJsonEncoder(json.JSONEncoder):
    """Custom JSON encoder supporting datetime, date, and pydantic models."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return super().default(obj)


class RedisCacheManager:
    """
    Centralized Redis Cache Manager with TTL-based data termination,
    pattern-based invalidation, and seamless in-memory fallback.
    """
    def __init__(self):
        self._client: Optional[Any] = None
        self._is_fallback: bool = False
        self._init_connection()

    def _init_connection(self):
        if not settings.CACHE_ENABLED:
            logger.info("[-] Caching is disabled via settings.")
            return

        if redis is not None:
            try:
                client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                )
                client.ping()
                self._client = client
                self._is_fallback = False
                logger.info(f"[+] Connected to live Redis instance at {settings.REDIS_URL}")
                return
            except Exception as e:
                logger.warning(f"[*] Live Redis connection failed ({e}). Attempting fallback...")

        if fakeredis is not None:
            try:
                self._client = fakeredis.FakeRedis(decode_responses=True)
                self._is_fallback = True
                logger.warning(
                    "[*] Engaged in-memory Redis fallback with 100% full TTL termination semantics."
                )
                return
            except Exception as fe:
                logger.error(f"[-] Failed to initialize cache fallback: {fe}")

        logger.warning("[-] Neither live Redis nor in-memory cache is available. Cache disabled.")
        self._client = None

    @property
    def client(self) -> Optional[Any]:
        return self._client

    @property
    def is_available(self) -> bool:
        return self._client is not None

    @property
    def is_fallback(self) -> bool:
        return self._is_fallback

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """
        Stores serialized value in Redis with strict TTL.
        Redis automatically terminates and deletes the key once TTL expires.
        """
        if not self.is_available or not settings.CACHE_ENABLED:
            return False

        try:
            serialized = json.dumps(value, cls=CacheJsonEncoder)
            self._client.set(name=key, value=serialized, ex=ttl)
            logger.debug(f"[CACHE SET] Key='{key}' with TTL={ttl}s")
            return True
        except Exception as e:
            logger.error(f"[CACHE SET ERROR] key='{key}': {e}")
            return False

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieves and deserializes data from Redis.
        Returns None if key has expired (terminated by TTL) or does not exist.
        """
        if not self.is_available or not settings.CACHE_ENABLED:
            return None

        try:
            raw = self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.error(f"[CACHE GET ERROR] key='{key}': {e}")
            return None

    def delete(self, key: str) -> bool:
        """Explicitly deletes/terminates a specific key immediately."""
        if not self.is_available:
            return False

        try:
            deleted_count = self._client.delete(key)
            return deleted_count > 0
        except Exception as e:
            logger.error(f"[CACHE DELETE ERROR] key='{key}': {e}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """
        Deletes all keys matching a wildcard pattern (e.g. 'plans:*', 'dashboard:*').
        Used for active data termination on write/mutation events.
        """
        if not self.is_available:
            return 0

        try:
            keys = list(self._client.keys(pattern))
            if not keys:
                return 0
            deleted_count = self._client.delete(*keys)
            logger.info(f"[CACHE INVALIDATE] Pattern='{pattern}' purged {deleted_count} keys.")
            return deleted_count
        except Exception as e:
            logger.error(f"[CACHE DELETE PATTERN ERROR] pattern='{pattern}': {e}")
            return 0

    def get_ttl(self, key: str) -> int:
        """
        Returns remaining Time-To-Live in seconds for a key:
        -2: Key does not exist (already terminated)
        -1: Key exists without expiration
        >=0: Remaining seconds until automatic termination
        """
        if not self.is_available:
            return -2

        try:
            return self._client.ttl(key)
        except Exception as e:
            logger.error(f"[CACHE TTL ERROR] key='{key}': {e}")
            return -2

    def get_all_active_keys(self, pattern: str = "*") -> List[Dict[str, Any]]:
        """Returns list of active cached keys with their remaining TTLs and types."""
        if not self.is_available:
            return []

        try:
            keys = list(self._client.keys(pattern))
            result = []
            for k in keys:
                ttl = self._client.ttl(k)
                result.append({
                    "key": k,
                    "ttl_seconds_remaining": ttl,
                    "is_expired": ttl == -2,
                })
            return result
        except Exception as e:
            logger.error(f"[CACHE GET KEYS ERROR]: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Provides cache health, backend type, and key counts."""
        if not self.is_available:
            return {
                "status": "DISABLED",
                "connected": False,
                "engine": "none",
                "total_keys": 0,
            }

        try:
            active_keys = self.get_all_active_keys("*")
            return {
                "status": "ACTIVE",
                "connected": True,
                "engine": "fakeredis_in_memory" if self._is_fallback else "redis_server",
                "redis_url": settings.REDIS_URL if not self._is_fallback else "in-memory-fallback",
                "total_cached_keys": len(active_keys),
                "keys": active_keys,
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "connected": False,
                "error": str(e),
            }

    def flush_all(self) -> bool:
        """Purges all keys across the current database."""
        if not self.is_available:
            return False
        try:
            self._client.flushdb()
            logger.warning("[CACHE FLUSH] Entire Redis cache database flushed.")
            return True
        except Exception as e:
            logger.error(f"[CACHE FLUSH ERROR]: {e}")
            return False

    # -------------------------------------------------------------------------
    # Token Revocation Management with TTL
    # -------------------------------------------------------------------------
    def revoke_token(self, token: str, exp_seconds: Optional[int] = None) -> bool:
        """
        Stores a revoked JWT token in Redis with TTL matching token expiration.
        Once token expires naturally, Redis terminates and deletes it automatically.
        """
        ttl = exp_seconds if exp_seconds and exp_seconds > 0 else (settings.TOKEN_EXP_TIME * 60)
        return self.set(f"revoked_token:{token}", "1", ttl=ttl)

    def is_token_revoked(self, token: str) -> bool:
        """Instant O(1) check if token is in the revocation blacklist."""
        if not self.is_available:
            return False
        try:
            return self._client.exists(f"revoked_token:{token}") > 0
        except Exception:
            return False


# Global Singleton Instance
redis_cache = RedisCacheManager()


def _build_cache_key(prefix: str, user_scoped: bool, kwargs: dict) -> str:
    key_parts = [prefix]
    if user_scoped:
        user = kwargs.get("user") or kwargs.get("admin")
        if user and hasattr(user, "id"):
            key_parts.append(f"u{user.id}")

    param_items = []
    for k, v in sorted(kwargs.items()):
        if k not in ["db", "user", "admin", "request", "response"] and v is not None:
            param_items.append(f"{k}:{v}")

    if param_items:
        key_parts.append("_".join(param_items))

    return ":".join(key_parts)


def cache_response(
    ttl: int = 300,
    prefix: str = "cache",
    user_scoped: bool = False,
):
    """
    Decorator for FastAPI route handlers to cache ApiResponse payloads in Redis.
    - Caches successful 200 OK responses with exact TTL.
    - When TTL passes, Redis terminates the cached key automatically.
    - If user_scoped=True, includes user ID in the key so users don't share private caches.
    """
    def decorator(func: Callable):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not settings.CACHE_ENABLED or not redis_cache.is_available:
                    return await func(*args, **kwargs)

                cache_key = _build_cache_key(prefix, user_scoped, kwargs)
                cached_data = redis_cache.get(cache_key)
                if cached_data is not None:
                    remaining_ttl = redis_cache.get_ttl(cache_key)
                    if isinstance(cached_data, dict):
                        cached_data["cached"] = True
                        cached_data["ttl_remaining"] = remaining_ttl
                        cached_data["_cached"] = True
                        cached_data["_ttl_remaining"] = remaining_ttl
                    return cached_data

                result = await func(*args, **kwargs)
                _save_result_to_cache(result, cache_key, ttl)
                return result

            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                if not settings.CACHE_ENABLED or not redis_cache.is_available:
                    return func(*args, **kwargs)

                cache_key = _build_cache_key(prefix, user_scoped, kwargs)
                cached_data = redis_cache.get(cache_key)
                if cached_data is not None:
                    remaining_ttl = redis_cache.get_ttl(cache_key)
                    if isinstance(cached_data, dict):
                        cached_data["cached"] = True
                        cached_data["ttl_remaining"] = remaining_ttl
                        cached_data["_cached"] = True
                        cached_data["_ttl_remaining"] = remaining_ttl
                    return cached_data

                result = func(*args, **kwargs)
                _save_result_to_cache(result, cache_key, ttl)
                return result

            return sync_wrapper

    return decorator


def _save_result_to_cache(result: Any, cache_key: str, ttl: int):
    if result is not None:
        data_to_cache = None
        if isinstance(result, dict) and result.get("status", 200) in [200, 201]:
            data_to_cache = result
        elif hasattr(result, "status") and getattr(result, "status") in [200, 201]:
            if hasattr(result, "model_dump"):
                data_to_cache = result.model_dump()
            elif hasattr(result, "__dict__"):
                data_to_cache = result.__dict__

        if data_to_cache is not None:
            redis_cache.set(cache_key, data_to_cache, ttl=ttl)

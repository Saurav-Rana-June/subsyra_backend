import time
import sys
from fastapi.testclient import TestClient
from main import app
from src.utils.redis_cache import redis_cache
from src.utils.db import LocalSession
from src.users.models import UserModel, UserRole
from src.utils.helpers import generate_access_token

client = TestClient(app)

print("=" * 60)
print("TEST 1: Redis Cache Engine & Initialization")
print("=" * 60)
stats = redis_cache.get_stats()
print(f"Status: {stats['status']}")
print(f"Engine: {stats['engine']}")
print(f"Connected: {stats['connected']}")
assert stats['connected'] is True, "Redis connection failed!"
print("[PASS] Redis cache engine initialized successfully.")

print("\n" + "=" * 60)
print("TEST 2: TTL Automatic Expiration & Data Termination")
print("=" * 60)
# Set a test key with 1 second TTL
redis_cache.set("test:short_key", {"msg": "expires_quickly"}, ttl=1)
ttl_initial = redis_cache.get_ttl("test:short_key")
print(f"Initial TTL for 'test:short_key': {ttl_initial}s")
assert ttl_initial >= 0, "TTL should be >= 0"
val_before = redis_cache.get("test:short_key")
assert val_before is not None, "Value should exist before TTL expiration"
print("[PASS] Key exists before TTL expiration.")

print("Waiting 1.2s for Redis TTL expiration...")
time.sleep(1.2)

val_after = redis_cache.get("test:short_key")
ttl_after = redis_cache.get_ttl("test:short_key")
print(f"Value after TTL: {val_after}, TTL after: {ttl_after}")
assert val_after is None, "Key must be terminated/deleted by Redis after TTL!"
assert ttl_after == -2, "Redis TTL for deleted/expired key should be -2"
print("[PASS] Redis successfully terminated and deleted expired key according to TTL.")

print("\n" + "=" * 60)
print("TEST 3: Active Route Caching (GET /api/plans)")
print("=" * 60)
# Clear any existing plans cache
redis_cache.delete_pattern("plans:*")

# 1st request -> Cache miss
res1 = client.get("/api/plans")
print(f"Request 1 Status: {res1.status_code}")
data1 = res1.json()
print(f"Request 1 Cached flag: {data1.get('cached') or data1.get('_cached')}")
assert (data1.get('cached') or data1.get('_cached')) is not True, "First request should be a cache miss"

# 2nd request -> Cache hit!
res2 = client.get("/api/plans")
print(f"Request 2 Status: {res2.status_code}")
data2 = res2.json()
print(f"Request 2 Cached flag: {data2.get('cached') or data2.get('_cached')}")
print(f"Request 2 TTL Remaining: {data2.get('ttl_remaining') or data2.get('_ttl_remaining')}s")
assert (data2.get('cached') or data2.get('_cached')) is True, "Second request should be a cache hit"
assert (data2.get('ttl_remaining') or data2.get('_ttl_remaining')) > 0, "TTL remaining should be > 0"
print("[PASS] GET /api/plans successfully cached in Redis with active TTL.")

print("\n" + "=" * 60)
print("TEST 4: Inspection Endpoints (GET /api/cache/status & /keys)")
print("=" * 60)
# Create or get admin user for auth header
db = LocalSession()
admin_user = db.query(UserModel).filter(UserModel.role == UserRole.ADMIN.value).first()
if not admin_user:
    # Use first user or promote
    admin_user = db.query(UserModel).first()
    if admin_user:
        admin_user.role = UserRole.ADMIN.value
        db.commit()
db.close()

token = generate_access_token(admin_user.id, admin_user.email_address, admin_user.mobile_number)
auth_headers = {"Authorization": f"Bearer {token}"}

res_status = client.get("/api/cache/status", headers=auth_headers)
print("Cache Status Response Code:", res_status.status_code)
status_data = res_status.json()
print("Cache Status Data:", status_data["data"])
assert res_status.status_code == 200
assert status_data["data"]["connected"] is True

res_keys = client.get("/api/cache/keys?pattern=plans:*", headers=auth_headers)
print("Cache Keys Matching 'plans:*':", res_keys.json())
assert res_keys.status_code == 200
active_keys = res_keys.json()["data"]
assert any("plans:list" in k["key"] for k in active_keys), "Cached plans key should be in keys list"
print("[PASS] Inspection endpoints accurately list cached keys and TTLs.")

print("\n" + "=" * 60)
print("TEST 5: Explicit Key Invalidation / Purge (DELETE /api/cache/keys)")
print("=" * 60)
res_del = client.delete("/api/cache/keys?pattern=plans:*", headers=auth_headers)
print("Delete Response:", res_del.json())
assert res_del.status_code == 200
assert res_del.json()["data"]["deleted_count"] >= 1

# Check if plans key is indeed terminated
check_val = redis_cache.get("plans:list")
assert check_val is None, "plans:list key should be completely deleted"
print("[PASS] Pattern termination actively purged matching keys.")

print("\n" + "=" * 60)
print("TEST 6: Token Revocation with TTL in Auth Flow")
print("=" * 60)
# Generate a test token
test_token = generate_access_token(admin_user.id, admin_user.email_address, admin_user.mobile_number)
test_headers = {"Authorization": f"Bearer {test_token}"}

# Verify request works with fresh token
res_auth_ok = client.get("/api/cache/status", headers=test_headers)
assert res_auth_ok.status_code == 200, "Request with valid token should succeed"
print("[PASS] Valid token is accepted.")

# Revoke token via Redis
redis_cache.revoke_token(test_token, exp_seconds=3600)
is_revoked = redis_cache.is_token_revoked(test_token)
ttl_token = redis_cache.get_ttl(f"revoked_token:{test_token}")
print(f"Is Token Revoked in Redis: {is_revoked}, TTL remaining: {ttl_token}s")
assert is_revoked is True, "Token must be marked revoked"

# Request with revoked token must now be rejected immediately with 401
res_auth_revoked = client.get("/api/cache/status", headers=test_headers)
print("Auth with Revoked Token Response:", res_auth_revoked.json())
assert res_auth_revoked.json()["status"] == 401
print("[PASS] Revoked token was immediately rejected by Redis auth check.")

print("\n" + "=" * 60)
print("ALL REDIS & TTL TERMINATION TESTS PASSED PERFECTLY!")
print("=" * 60)

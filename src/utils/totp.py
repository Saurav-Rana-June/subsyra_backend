import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import List
from urllib.parse import quote


def generate_totp_secret(length: int = 20) -> str:
    """Generates a Base32-encoded random TOTP shared secret."""
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def build_otpauth_uri(secret: str, email_address: str, issuer: str = "Subsyra") -> str:
    """Builds a standard otpauth:// URI compatible with authenticator apps."""
    label = f"{quote(issuer)}:{quote(email_address)}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def _compute_totp_at(secret: str, counter: int, digits: int = 6) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits)


def generate_current_totp(secret: str, for_time: float | None = None) -> str:
    """Computes the current 6-digit RFC 6238 TOTP code for a given secret."""
    timestamp = time.time() if for_time is None else for_time
    counter = int(timestamp // 30)
    return _compute_totp_at(secret, counter)


def verify_totp_code(secret: str, code: str, window: int = 1, for_time: float | None = None) -> bool:
    """Verifies a 6-digit TOTP code against the secret with +/- window step drift."""
    normalized = (code or "").strip().replace(" ", "").replace("-", "")
    if not normalized.isdigit() or len(normalized) != 6 or not secret:
        return False

    timestamp = time.time() if for_time is None else for_time
    current_counter = int(timestamp // 30)

    for offset in range(-window, window + 1):
        expected = _compute_totp_at(secret, current_counter + offset)
        if hmac.compare_digest(expected, normalized):
            return True
    return False


def generate_recovery_codes(count: int = 6) -> List[str]:
    """Generates cryptographically random one-time 2FA recovery codes."""
    codes: List[str] = []
    for _ in range(count):
        p1 = secrets.randbelow(9000) + 1000
        p2 = secrets.randbelow(9000) + 1000
        codes.append(f"SUB-{p1}-{p2}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Returns deterministic SHA-256 digest of a normalized recovery code."""
    normalized = (code or "").strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mask_recovery_code(code: str) -> str:
    """Returns a non-sensitive display hint for a recovery code."""
    parts = code.split("-")
    if len(parts) == 3:
        return f"{parts[0]}-****-{parts[2]}"
    return "****"


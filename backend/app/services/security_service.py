import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "invite_code",
    "code_hash",
    "token",
    "token_hash",
    "session_token",
    "csrf_token",
    "secret",
    "api_key",
    "temporary_password",
    "file_content",
}

password_hasher = PasswordHasher()


class SecurityConfigurationError(RuntimeError):
    pass


def require_auth_secret() -> bytes:
    secret = settings.auth_secret_key
    if len(secret) < 32:
        raise SecurityConfigurationError("AUTH_SECRET_KEY 未配置或长度不足")
    return secret.encode("utf-8")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("账号需为 3 至 50 位字母、数字、点、下划线或连字符")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < settings.password_min_length:
        raise ValueError(f"密码长度不能少于 {settings.password_min_length} 位")
    if len(password) > 256:
        raise ValueError("密码长度不能超过 256 位")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def generate_invite_code() -> str:
    return f"IF-{secrets.token_urlsafe(18)}"


def generate_temporary_password() -> str:
    return f"If!{secrets.token_urlsafe(15)}"


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def keyed_digest(value: str, purpose: str) -> str:
    message = f"{purpose}:{value}".encode("utf-8")
    return hmac.new(require_auth_secret(), message, hashlib.sha256).hexdigest()


def invite_code_hash(code: str) -> str:
    return keyed_digest(code.strip(), "invite-code")


def invite_code_hint(code: str) -> str:
    stripped = code.strip()
    if len(stripped) <= 6:
        return f"{stripped[:2]}…{stripped[-1:]}"
    return f"{stripped[:4]}…{stripped[-3:]}"


def scope_hash(scope_type: str, value: str) -> str:
    return keyed_digest(value.strip().lower(), f"rate-limit:{scope_type}")


def create_public_csrf_token() -> str:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{timestamp}.{nonce}"
    signature = keyed_digest(payload, "public-csrf")
    return f"{payload}.{signature}"


def verify_public_csrf_token(token: str) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    timestamp, nonce, signature = parts
    if not timestamp.isdigit() or not nonce:
        return False
    if abs(int(time.time()) - int(timestamp)) > settings.csrf_ttl_seconds:
        return False
    expected = keyed_digest(f"{timestamp}.{nonce}", "public-csrf")
    return hmac.compare_digest(signature, expected)


def sanitize_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_details(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [sanitize_details(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_details(item) for item in value]
    return value


def sanitized_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(sanitize_details(value), ensure_ascii=False)

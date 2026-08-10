"""短期签名 capability token（阶段 5A-1 补修）。

以 ENGINEERING_MCP_INTERNAL_TOKEN 为 HMAC 签名密钥，为指定 user_id 签发
短期 token；服务端校验签名、有效期与格式后把真实 user_id 写入
AccessToken.subject。禁止把原始共享密钥本身作为可直接调用工具的 bearer。

格式：v1.<base64url(json payload)>.<base64url(hmac_sha256(sig_input, secret))>
payload: {"sub": str(user_id), "iat": int, "exp": int, "nonce": str}
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from app.core.config import settings

TOKEN_VERSION = "v1"
DEFAULT_TTL_SECONDS = 300  # 短期：5 分钟


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(sig_input: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), sig_input.encode("utf-8"),
                      hashlib.sha256).digest()
    return _b64url(digest)


def issue_capability_token(
    user_id: int,
    *,
    secret: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> str:
    """为 user_id 签发短期签名 capability token。"""
    signing_key = secret if secret is not None else settings.engineering_mcp_internal_token
    if not signing_key:
        raise ValueError("ENGINEERING_MCP_INTERNAL_TOKEN 未配置，无法签发 capability token")

    current = now if now is not None else int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": current,
        "exp": current + ttl_seconds,
        "nonce": uuid.uuid4().hex,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig_input = f"{TOKEN_VERSION}.{body}"
    return f"{sig_input}.{_sign(sig_input, signing_key)}"


def verify_capability_token(
    token: str, secret: str | None = None, *, now: int | None = None
) -> dict[str, Any] | None:
    """校验 capability token：格式、签名（compare_digest）、有效期。

    任何失败返回 None（调用方映射为 401）。
    """
    signing_key = secret if secret is not None else settings.engineering_mcp_internal_token
    if not signing_key or not token:
        return None

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        return None

    sig_input = f"{parts[0]}.{parts[1]}"
    expected = _sign(sig_input, signing_key)
    if not hmac.compare_digest(parts[2], expected):
        return None

    try:
        payload = json.loads(_unb64url(parts[1]).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    sub = payload.get("sub")
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(sub, str) or not sub.isdigit():
        return None
    if not isinstance(exp, int) or not isinstance(iat, int):
        return None

    current = now if now is not None else int(time.time())
    if exp < current:
        return None  # 过期

    return payload

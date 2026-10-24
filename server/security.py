"""认证基础设施：PBKDF2 口令哈希 + HMAC-SHA256 签名令牌（JWT 格式）。

不引第三方 jwt 依赖，避免离线环境装包失败；算法与标准 JWT 兼容，
后续如需接入企业微信 SSO，只需替换 issue_token 的 subject 来源。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from .config import settings

PBKDF2_ROUNDS = 240_000


# ---------------------------- 口令 ----------------------------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, password_hash)


# ---------------------------- 令牌 ----------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(payload: dict[str, Any], ttl_seconds: int | None = None) -> str:
    now = int(time.time())
    body = {
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + (ttl_seconds or settings.token_ttl_minutes * 60),
        "jti": secrets.token_hex(8),
        **payload,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    seg = f"{_b64e(json.dumps(header, separators=(',', ':')).encode())}." \
          f"{_b64e(json.dumps(body, separators=(',', ':')).encode())}"
    sig = hmac.new(settings.jwt_secret.encode(), seg.encode(), hashlib.sha256).digest()
    return f"{seg}.{_b64e(sig)}"


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict[str, Any]:
    try:
        h, p, s = token.split(".")
    except ValueError as exc:
        raise TokenError("令牌格式错误") from exc
    expect = hmac.new(settings.jwt_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64e(expect), s):
        raise TokenError("令牌签名无效")
    try:
        body = json.loads(_b64d(p))
    except Exception as exc:  # noqa: BLE001
        raise TokenError("令牌内容无法解析") from exc
    if body.get("iss") != settings.jwt_issuer:
        raise TokenError("签发方不匹配")
    if int(body.get("exp", 0)) < int(time.time()):
        raise TokenError("令牌已过期")
    return body


def new_request_id() -> str:
    return secrets.token_hex(8)


def gen_temp_password() -> str:
    return "Fin@" + secrets.token_urlsafe(6)

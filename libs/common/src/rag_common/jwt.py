"""최소 HS256 JWT (stdlib only). Web Chat access token 전용 — docs/TDD.md §7.1.5.

외부 IdP 연동은 범위 외이므로 alg 는 HS256 하나만 허용한다 (alg=none/RS* 거부).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class JWTError(Exception):
    """서명 불일치·만료·형식 오류. 메시지에 토큰/키를 포함하지 않는다."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode(claims: dict[str, Any], secret: bytes, *, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {**claims, "iat": now, "exp": now + ttl_seconds}
    header = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64e(sig)}"


def decode(token: str, secret: bytes, *, leeway: int = 5) -> dict[str, Any]:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
        header = json.loads(_b64d(header_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise JWTError("malformed token") from exc
    if header.get("alg") != "HS256":
        raise JWTError("unsupported alg")
    expected = hmac.new(secret, f"{header_b64}.{body_b64}".encode(), hashlib.sha256).digest()
    try:
        sig = _b64d(sig_b64)
    except ValueError as exc:
        raise JWTError("malformed signature") from exc
    if not hmac.compare_digest(sig, expected):
        raise JWTError("invalid signature")
    try:
        claims: dict[str, Any] = json.loads(_b64d(body_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise JWTError("malformed payload") from exc
    if int(claims.get("exp", 0)) + leeway < int(time.time()):
        raise JWTError("expired")
    return claims

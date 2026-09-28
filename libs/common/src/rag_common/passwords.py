"""Web Chat 비밀번호 처리 — stdlib only (폐쇄망: 추가 wheel 없음). docs/TDD.md §7.1.5.

1. 클라이언트 prehash (chat-web `src/shared/crypto/prehash.ts` 와 바이트 단위 동일):
     salt    = SHA-256("aiops-chat:" + workspace_slug + ":" + normalized_email)
     prehash = base64(PBKDF2-HMAC-SHA256(password, salt, 600_000, 32))
   원문 비밀번호는 브라우저를 떠나지 않는다. 서버는 prehash 를 "비밀번호"로 취급한다.
2. 서버 저장: scrypt(HMAC-SHA256(pepper, prehash), random salt) — pepper 는 Secret 파일.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

PREHASH_ITERATIONS = 600_000
PREHASH_BYTES = 32
_SALT_PREFIX = "aiops-chat:"  # 이식 원본(aiops_chatbot)과 동일 — 변경 시 전 사용자 재설정 필요

_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_SCHEME = "scrypt"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def compute_prehash(
    workspace_slug: str, email: str, password: str, *, iterations: int = PREHASH_ITERATIONS
) -> str:
    """서버 측 prehash 계산 — 관리자 사용자 생성/seed 전용 (로그인 경로에서는 쓰지 않는다)."""
    salt = hashlib.sha256(
        f"{_SALT_PREFIX}{workspace_slug}:{normalize_email(email)}".encode()
    ).digest()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, PREHASH_BYTES)
    return base64.b64encode(dk).decode()


def _peppered(pepper: bytes, prehash: str) -> bytes:
    return hmac.new(pepper, prehash.encode(), hashlib.sha256).digest()


def _scrypt(material: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(material, salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=32)


def hash_prehash(prehash: str, pepper: bytes) -> str:
    salt = os.urandom(16)
    dk = _scrypt(_peppered(pepper, prehash), salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    b64 = base64.urlsafe_b64encode
    return f"{_SCHEME}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt).decode()}${b64(dk).decode()}"


_DUMMY_HASH: str | None = None


def verify_prehash(stored: str | None, prehash: str, pepper: bytes) -> bool:
    """상수 시간 비교. 저장 해시가 없어도 동일 비용을 소모한다 (사용자 열거 방지)."""
    global _DUMMY_HASH
    if not stored:
        if _DUMMY_HASH is None:
            _DUMMY_HASH = hash_prehash("dummy-prehash-for-timing", b"dummy")
        stored = _DUMMY_HASH
        _verify(stored, prehash, pepper)
        return False
    return _verify(stored, prehash, pepper)


def _verify(stored: str, prehash: str, pepper: bytes) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(dk_b64)
        got = _scrypt(_peppered(pepper, prehash), salt, int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)

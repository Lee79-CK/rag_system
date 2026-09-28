"""rag_common.passwords / rag_common.jwt 단위 테스트 (FR-WEB-001 로그인 기반)."""

from __future__ import annotations

import time

import pytest
from rag_common import jwt
from rag_common.passwords import compute_prehash, hash_prehash, verify_prehash

# chat-web `src/shared/crypto/prehash.ts` (aiops_chatbot 원본) 를 Node 24 로 실행해 얻은 값.
# 두 구현이 어긋나면 브라우저 로그인이 전부 실패하므로 고정 벡터로 회귀를 막는다.
TS_VECTOR_1000 = "kzY2+IOcFMH0IQIxPOQDNVqFEAVCap2agyuP5CmYLic="


def test_fr_web_001_prehash_matches_web_client_vector():
    got = compute_prehash("rag", "Hong@Example.com ", "Aiops!Demo2026#", iterations=1000)
    assert got == TS_VECTOR_1000


def test_hash_verify_roundtrip_and_pepper_bound():
    pre = compute_prehash("rag", "a@b.c", "pw", iterations=10)
    stored = hash_prehash(pre, b"pepper")
    assert stored.startswith("scrypt$")
    assert pre not in stored
    assert verify_prehash(stored, pre, b"pepper")
    assert not verify_prehash(stored, pre, b"other-pepper")
    assert not verify_prehash(stored, pre + "x", b"pepper")


def test_verify_without_stored_hash_is_false():
    assert verify_prehash(None, "anything-long-enough", b"p") is False
    assert verify_prehash("garbage", "anything-long-enough", b"p") is False


def test_jwt_roundtrip():
    tok = jwt.encode({"sub": "u1"}, b"k" * 32, ttl_seconds=60)
    assert jwt.decode(tok, b"k" * 32)["sub"] == "u1"


def test_jwt_rejects_bad_signature_and_alg():
    tok = jwt.encode({"sub": "u1"}, b"k" * 32, ttl_seconds=60)
    with pytest.raises(jwt.JWTError):
        jwt.decode(tok, b"x" * 32)
    header, body, _ = tok.split(".")
    none_alg = jwt._b64e(b'{"alg":"none"}') + "." + body + "."
    with pytest.raises(jwt.JWTError):
        jwt.decode(none_alg, b"k" * 32)
    with pytest.raises(jwt.JWTError):
        jwt.decode("not-a-token", b"k" * 32)


def test_jwt_expired(monkeypatch):
    tok = jwt.encode({"sub": "u1"}, b"k" * 32, ttl_seconds=1)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 3600)
    with pytest.raises(jwt.JWTError):
        jwt.decode(tok, b"k" * 32)

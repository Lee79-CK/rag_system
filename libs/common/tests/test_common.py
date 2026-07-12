"""libs/common 단위 테스트."""

from __future__ import annotations

from rag_common import (
    TTLCache,
    chunk_point_id,
    dumps,
    loads,
    new_request_id,
    new_trace_id,
    sha256_hex,
)


def test_ids_have_prefixes_and_are_unique():
    assert new_request_id().startswith("req-")
    assert new_trace_id().startswith("trace-")
    assert new_request_id() != new_request_id()


def test_chunk_point_id_is_deterministic():
    # 멱등 Upsert (FR-IDX-006): 동일 chunk_id는 항상 동일 point id.
    a = chunk_point_id("v1-00007")
    b = chunk_point_id("v1-00007")
    assert a == b
    assert chunk_point_id("v1-00008") != a


def test_sha256_hex_prefixed():
    h = sha256_hex("hello")
    assert h.startswith("sha256:")
    assert h == sha256_hex(b"hello")


def test_json_roundtrip():
    assert loads(dumps({"a": 1, "b": [1, 2]})) == {"a": 1, "b": [1, 2]}


def test_ttl_cache_expires_with_injected_clock():
    now = {"t": 0.0}
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=60, clock=lambda: now["t"])
    cache.set("k", 42)
    assert cache.get("k") == 42
    now["t"] = 59.9
    assert cache.get("k") == 42
    now["t"] = 60.0
    assert cache.get("k") is None  # 만료


def test_ttl_cache_invalidate():
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None

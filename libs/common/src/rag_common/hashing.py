"""해시 유틸. Webhook payload는 원문 미저장, hash만 (NFR-DATA-007)."""

from __future__ import annotations

import hashlib


def sha256_hex(data: str | bytes) -> str:
    """`sha256:<hex>` 형태의 접두 포함 해시 문자열을 반환한다."""
    raw = data.encode() if isinstance(data, str) else data
    return "sha256:" + hashlib.sha256(raw).hexdigest()

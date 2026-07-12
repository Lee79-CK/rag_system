"""orjson 기반 JSON 헬퍼 (§3.1). FastAPI 비종속 — 순수 직렬화만."""

from __future__ import annotations

from typing import Any

import orjson


def dumps(obj: Any) -> bytes:
    return orjson.dumps(obj)


def loads(data: str | bytes) -> Any:
    return orjson.loads(data)

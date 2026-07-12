"""고정 윈도우 Rate Limit (docs/TDD.md §10, §32).

Redis `INCR + EXPIRE`. 질문/채널/피드백 각각 별도 키를 사용한다.
"""

from __future__ import annotations

from typing import Any


async def allow(redis: Any, key: str, limit: int, window: int = 60) -> bool:
    """윈도우 내 요청이 limit 이하이면 True. 첫 요청 시 TTL을 설정한다."""
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    return count <= limit

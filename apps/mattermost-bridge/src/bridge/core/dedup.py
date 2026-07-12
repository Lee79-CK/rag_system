"""Redis 기반 이벤트 중복 제거 (docs/TDD.md §7.1.1 step7, FR-MM-006).

1차 방어선: Redis `SET NX EX`. (2차: mattermost_events.post_id UNIQUE — §5)
"""

from __future__ import annotations

from typing import Any

_DEDUP_TTL_SECONDS = 86400  # 24h


def _key(post_id: str) -> str:
    return f"mm:event:{post_id}"


async def is_duplicate(redis: Any, post_id: str, ttl: int = _DEDUP_TTL_SECONDS) -> bool:
    """`SET key NX EX=ttl`. 이미 존재하면(=중복) True를 반환한다."""
    was_set = await redis.set(_key(post_id), "1", nx=True, ex=ttl)
    # redis-py: 새로 설정되면 True, 이미 존재해 설정 실패하면 None.
    return not bool(was_set)


async def delete_dedup(redis: Any, post_id: str) -> None:
    """INSERT 실패 시 롤백 — dedup key를 삭제해 재시도를 허용한다 (§7.1.1 MUST)."""
    await redis.delete(_key(post_id))

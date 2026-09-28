"""질문 중복 제거 (docs/TDD.md §7.1.1 step3, FR-WEB-006).

chat-web 은 전송마다 `client_id`(UUID)를 붙인다. 재전송/더블클릭/네트워크 재시도로
같은 client_id 가 다시 오면 새 Post·Job 을 만들지 않고 기존 Post 를 반환한다.
1차 방어선: Redis `SET NX EX`. (2차: chat_posts (user_id, client_id) UNIQUE — §5)
"""

from __future__ import annotations

from typing import Any

_DEDUP_TTL_SECONDS = 86400  # 24h
PENDING = "pending"


def _key(user_id: str, client_id: str) -> str:
    return f"chat:client:{user_id}:{client_id}"


async def claim(
    redis: Any, user_id: str, client_id: str, ttl: int = _DEDUP_TTL_SECONDS
) -> str | None:
    """선점 성공 시 None, 이미 존재하면 저장된 값(post_id 또는 'pending')을 반환한다."""
    was_set = await redis.set(_key(user_id, client_id), PENDING, nx=True, ex=ttl)
    if was_set:
        return None
    existing = await redis.get(_key(user_id, client_id))
    return existing or PENDING


async def resolve(redis: Any, user_id: str, client_id: str, post_id: str) -> None:
    await redis.set(_key(user_id, client_id), post_id, xx=True, keepttl=True)


async def release(redis: Any, user_id: str, client_id: str) -> None:
    """INSERT 실패 시 롤백 — 재시도를 허용한다 (§7.1.1 MUST)."""
    await redis.delete(_key(user_id, client_id))

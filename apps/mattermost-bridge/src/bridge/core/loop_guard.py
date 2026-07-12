"""Loop Guard — Bot 자기 메시지 재수신 차단 (docs/TDD.md §7.1.1 step5, FR-MM-007)."""

from __future__ import annotations


def is_loop_message(user_name: str | None, bot_username: str | None) -> bool:
    """메시지 작성자가 Bot 계정이면 True (무한 루프 방지)."""
    if not user_name:
        return False
    return user_name.strip().casefold() == (bot_username or "").strip().casefold()

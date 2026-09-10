"""Settings 비밀값 노출 금지 (CLAUDE.md 규칙 3, TDD §3.2)."""

from __future__ import annotations

from admin.core.config import Settings


def test_config_password_not_in_repr():
    s = Settings(POSTGRES_PASSWORD="super-secret-pw")  # type: ignore[call-arg]
    assert "super-secret-pw" not in repr(s)
    assert "super-secret-pw" not in str(s.model_dump())
    assert "super-secret-pw" in s.sqlalchemy_url

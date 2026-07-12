"""Bridge 설정 (docs/TDD.md §10, docs/README.md §3.2).

env 키는 SSOT(부록 B / TDD §10)를 그대로 사용한다. Secret은 file mount에서 로딩하고
`SecretStr`/bytes로만 보관하여 로그·응답·repr에 노출하지 않는다 (§3.2, §11 #2).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(path: str) -> str:
    """Secret file 내용을 반환한다. 파일이 없으면(테스트 등) 빈 문자열을 허용한다."""
    if path and os.path.isfile(path):
        return Path(path).read_text(encoding="utf-8").strip()
    return ""


class Settings(BaseSettings):
    """env → Settings. 키 이름은 TDD §10 / README §3.2 와 1:1 (임의 변경 금지)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Infra
    redis_url: str = "redis://localhost:6379/0"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "rag"

    # Mattermost Bridge
    mattermost_outgoing_token_secret_file: str = ""
    bridge_allowed_source_cidrs: str = ""
    bridge_bot_username: str = "RAG Assistant"
    bridge_binding_cache_ttl_seconds: int = 60
    mattermost_default_trigger_word: str = "!rag"
    mattermost_max_post_chars: int = 12000

    # Rate Limit
    rate_limit_per_user_per_min: int = 10
    rate_limit_per_channel_per_min: int = 30
    rate_limit_feedback_per_user_per_min: int = 20

    # Feedback (v1.1)
    feedback_enabled: bool = True
    feedback_signing_key_file: str = ""
    bridge_internal_url: str = "http://localhost:8001"

    # --- derived / secret accessors (값 자체는 로그/응답에 노출 금지) ---

    def outgoing_token(self) -> str:
        """Outgoing Webhook 검증 토큰 (Secret file). 미설정 시 빈 문자열."""
        return _read_secret_file(self.mattermost_outgoing_token_secret_file)

    def feedback_signing_key(self) -> bytes:
        """피드백 HMAC 서명 키 (Secret file) → bytes."""
        return _read_secret_file(self.feedback_signing_key_file).encode("utf-8")

    def allowed_cidrs(self) -> list[str]:
        """comma-separated CIDR 문자열을 파싱한다. 빈 값이면 빈 리스트(=허용 개방)."""
        return [c.strip() for c in self.bridge_allowed_source_cidrs.split(",") if c.strip()]

    def feedback_action_url(self) -> str:
        """답변 버튼이 POST할 actions endpoint (§7.1.4)."""
        return f"{self.bridge_internal_url.rstrip('/')}/integrations/mattermost/v1/actions"

    def postgres_dsn(self) -> str:
        """SQLAlchemy(psycopg) DSN. 비밀번호는 여기서만 노출되며 로그에 남기지 않는다."""
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""chat-gateway 설정 (docs/TDD.md §10).

env 키는 TDD §10 이 SSOT. Secret(JWT 키/pepper/피드백 서명 키)은 file mount 에서 로딩하고
bytes/SecretStr 로만 보관하여 로그·응답·repr 에 노출하지 않는다 (§3.2, §11 #2).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REFRESH_COOKIE = "rag_rt"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _read_secret_file(path: str) -> str:
    """Secret file 내용을 반환한다. 파일이 없으면(테스트 등) 빈 문자열을 허용한다."""
    if path and os.path.isfile(path):
        return Path(path).read_text(encoding="utf-8").strip()
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infra
    redis_url: str = "redis://localhost:6379/0"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "rag"

    # Web Chat
    chat_workspace_slug: str = (
        "rag"  # prehash salt 구성요소 — chat-web NEXT_PUBLIC_WORKSPACE_SLUG 와 동일
    )
    chat_workspace_name: str = "RAG Assistant"
    chat_default_trigger_word: str = "!rag"
    chat_max_post_chars: int = 12000
    chat_cors_origins: str = "http://localhost:3000"  # socket.io Origin 허용 (dev 교차 출처)

    # Auth
    jwt_secret_file: str = ""
    password_pepper_file: str = ""
    chat_access_ttl_seconds: int = 900  # 15m
    refresh_ttl_days: int = 7
    cookie_secure: bool = True
    login_max_clock_skew_seconds: int = 300

    # Rate Limit
    rate_limit_per_user_per_min: int = 10
    rate_limit_per_channel_per_min: int = 30
    rate_limit_feedback_per_user_per_min: int = 20
    rate_limit_login_per_min: int = 10

    # Feedback (v1.1)
    feedback_enabled: bool = True
    feedback_signing_key_file: str = ""

    # --- secret accessors (값 자체는 로그/응답에 노출 금지) ---

    def jwt_secret(self) -> bytes:
        return _read_secret_file(self.jwt_secret_file).encode("utf-8")

    def password_pepper(self) -> bytes:
        return _read_secret_file(self.password_pepper_file).encode("utf-8")

    def feedback_signing_key(self) -> bytes:
        return _read_secret_file(self.feedback_signing_key_file).encode("utf-8")

    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.chat_cors_origins.split(",") if o.strip()]

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

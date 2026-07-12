"""admin-api 설정 (docs/TDD.md §10, §7.5).

환경변수 키는 TDD §10 + PRD 부록 B가 SSOT. 임의 변경 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- PostgreSQL (부록 B) ---
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="rag", alias="POSTGRES_USER")
    postgres_password: str = Field(default="rag-dev-only", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="rag", alias="POSTGRES_DB")
    # 명시적 override (예: 테스트/특수 배포). 설정 시 위 5개 키보다 우선.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # --- 문서 저장 (DEC-004 NFS PVC) ---
    document_storage_path: str = Field(default="/data/documents", alias="DOCUMENT_STORAGE_PATH")
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")

    # --- Feedback / 내부 URL (연결 테스트에 사용) ---
    bridge_internal_url: str = Field(default="http://localhost:8001", alias="BRIDGE_INTERNAL_URL")

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

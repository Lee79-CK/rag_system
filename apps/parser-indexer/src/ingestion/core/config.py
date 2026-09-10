"""parser-indexer 설정 — docs/TDD.md §10 (env keys), §7.7.

키 이름은 TDD §10 + PRD 부록 B가 SSOT다. 임의로 변경하지 않는다 (§10).
오프라인 규칙(§3.4): 런타임에 외부 네트워크를 호출하지 않는다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Qdrant ----
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "rag_chunks_v1"
    qdrant_timeout: float = 30.0
    vector_dim: int = 1024

    # ---- Embedding API ----
    embedding_api_url: str = "http://localhost:8004"
    embedding_max_batch: int = 64
    embedding_timeout: float = 30.0

    # ---- Chunking (§7.7 step 4) ----
    chunk_size: int = 800  # 토큰 근사 목표
    chunk_overlap: int = 120
    # transformers/tokenizer 미설치 환경에서 토큰을 문자로 근사 (chars ≈ tokens * factor).
    chars_per_token: float = 3.3
    # 최소 청크 토큰 수 — 미만이면 이웃과 병합 (§7.7 step 4).
    min_chunk_tokens: int = 50

    # ---- PostgreSQL ----
    database_url: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: SecretStr = SecretStr(
        "rag-dev-only"
    )  # repr/log 노출 금지 (CLAUDE.md 규칙 3)
    postgres_db: str = "rag"

    # ---- 문서 저장소 (NFS PVC — §7.5 DEC-004) ----
    document_storage_path: str = "/data/documents"

    # ---- OCR (기본 비활성 — DEC-005) ----
    ocr_enabled: bool = False

    def sqlalchemy_url(self) -> str:
        """DATABASE_URL 우선, 없으면 POSTGRES_* 조합으로 psycopg URL 생성."""
        if self.database_url:
            return self.database_url
        pw = self.postgres_password.get_secret_value()  # DSN 조립 시에만 노출
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

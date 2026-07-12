"""rag-api 설정 (pydantic-settings). 키 이름은 TDD §10 + README §3.2가 SSOT."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infra
    redis_url: str = "redis://localhost:6379/0"
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: str = "rag-dev-only"
    postgres_db: str = "rag"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "rag_chunks_v1"

    # Internal services
    embedding_api_url: str = "http://localhost:8004"
    reranker_api_url: str = "http://localhost:8005"
    vllm_api_url: str = "http://localhost:8010/v1"
    llm_served_model_name: str = "internal-rag-llm"
    bridge_internal_url: str = "http://localhost:8001"

    # Retrieval / generation
    vector_top_k: int = 30
    rerank_top_n: int = 8
    max_context_tokens: int = 8192
    max_output_tokens: int = 1024
    safety_margin_tokens: int = 256
    similarity_threshold: float = 0.0
    rerank_score_threshold: float = 0.0
    tokenizer_path: str = "/models/llm/main"
    chat_max_concurrency: int = 15
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 120.0

    # Feedback (v1.1)
    feedback_enabled: bool = True
    feedback_signing_key_file: str = "./secrets/rag/feedback-signing-key"

    # Incoming Webhook secret files (secret_ref → 파일) — §7.1.2
    mattermost_secret_dir: str = "./secrets/mattermost"

    # Timeouts
    http_connect_timeout: float = 3.0
    http_read_timeout: float = 30.0

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

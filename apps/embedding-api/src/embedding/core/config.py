"""embedding-api 설정 — docs/TDD.md §10 (env keys).

오프라인 규칙(§3.4): 모델은 로컬 경로(EMBEDDING_MODEL_PATH)만 로딩한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 모델 경로 (HF Hub ID 금지 — §3.4).
    embedding_model_path: str = "/models/embedding/bge-m3"
    # 모델 미배치 로컬 환경에서 결정론적 mock 엔진 강제.
    embedding_mock: bool = False
    # batch size 상한 — 초과 요청은 내부 분할 (§7.3).
    embedding_max_batch: int = 64

    @property
    def model_name(self) -> str:
        """응답 model 필드에 노출할 안정적 이름."""
        return "bge-m3"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""reranker-api 설정 — docs/TDD.md §10 (env keys).

오프라인 규칙(§3.4): 모델은 로컬 경로(RERANKER_MODEL_PATH)만 로딩한다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 모델 경로 (HF Hub ID 금지 — §3.4).
    reranker_model_path: str = "/models/reranker/bge-reranker-v2-m3"
    # 모델 미배치 로컬 환경에서 결정론적 mock 엔진 강제.
    reranker_mock: bool = False
    # 입력 후보 상한 (§7.4). 초과 요청은 422 거부.
    rerank_max_candidates: int = 50
    # cross-encoder max_length (§7.4).
    reranker_max_length: int = 1024

    @property
    def model_name(self) -> str:
        return "bge-reranker-v2-m3"


@lru_cache
def get_settings() -> Settings:
    return Settings()

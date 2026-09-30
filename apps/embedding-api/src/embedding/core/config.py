"""embedding-api 설정 — docs/TDD.md §10 (env keys).

오프라인 규칙(§3.4): 모델은 로컬 경로(EMBEDDING_MODEL_PATH)만 로딩한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 로컬 모델 경로 (HF Hub ID 금지 — §3.4).
    embedding_model_path: str = "/models/embedding/bge-m3"
    # 모델 미배치 로컬 환경에서 결정론적 mock 엔진 강제.
    embedding_mock: bool = False
    # batch size 상한 — 초과 요청은 내부 분할 (§7.3).
    embedding_max_batch: int = 64
    # 입력 최대 토큰(초과분 절단). FlagEmbedding ≥1.3 의 encode 기본값은 512 로, 한글 청크
    # (CHARS_PER_TOKEN=3.3 기준 최대 ≈1,400 tok)의 뒷부분이 벡터에 반영되지 않는다 → 명시 전달.
    embedding_max_length: int = 2048
    # 비대칭 모델용 접두어 (예: snowflake-arctic-embed-l-v2.0-ko → EMBEDDING_QUERY_PREFIX="query: ").
    # bge-m3 / KURE-v1 은 접두어 없음(빈 값). 가이드 §5.1.2.
    embedding_query_prefix: str = ""
    embedding_passage_prefix: str = ""

    @property
    def model_name(self) -> str:
        """응답 model 필드 = 모델 디렉터리 이름 (bge-m3, kure-v1 …) — 어떤 모델로 색인됐는지 로그로 추적."""
        return Path(self.embedding_model_path).name or "embedding"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""임베딩 엔진 추상화 — docs/TDD.md §7.3.

- Mock 활성화(EMBEDDING_MOCK) 또는 모델 경로 부재 → MockEngine (결정론적).
- 그 외 → RealEngine: FlagEmbedding을 __init__ 시점에 lazy-import.
  (로컬 Intel macOS엔 FlagEmbedding/torch 미설치 — import 시점에 실패하면 안 되므로
   모듈 최상단이 아니라 엔진 생성 시점에만 import 한다.)
- dim은 1024 고정 — BGE-M3 및 그 파인튜닝(KURE-v1 등 XLM-R large 계열)만 교체 가능 (가이드 §5.1.2).
- input_type(query/passage)별 접두어는 비대칭 모델용 (기본 빈 값).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from itertools import batched
from typing import Literal

import numpy as np

from embedding.core.config import Settings

EMBEDDING_DIM = 1024

InputType = Literal["query", "passage"]


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class Engine(ABC):
    """임베딩 엔진 인터페이스."""

    model_name: str
    dim: int = EMBEDDING_DIM

    def __init__(self, settings: Settings) -> None:
        self._prefixes: dict[str, str] = {
            "query": settings.embedding_query_prefix,
            "passage": settings.embedding_passage_prefix,
        }

    def embed(
        self, texts: list[str], *, normalize: bool, input_type: InputType = "passage"
    ) -> list[list[float]]:
        """텍스트 리스트 → dense 벡터 리스트. input_type 접두어를 붙여 엔진에 넘긴다."""
        if not texts:
            return []
        prefix = self._prefixes.get(input_type, "")
        return self._encode(
            [f"{prefix}{t}" for t in texts] if prefix else texts, normalize=normalize
        )

    @abstractmethod
    def _encode(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        raise NotImplementedError


class MockEngine(Engine):
    """결정론적 mock 엔진. 동일 텍스트 → 동일 벡터 (테스트/로컬용)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.model_name = f"{settings.model_name}-mock"
        self.dim = EMBEDDING_DIM

    @staticmethod
    def _seed(text: str) -> int:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _vector(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(self._seed(text))
        return rng.standard_normal(EMBEDDING_DIM).astype(np.float64)

    def _encode(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        vectors = np.stack([self._vector(t) for t in texts])
        if normalize:
            vectors = _l2_normalize(vectors)
        return vectors.tolist()


class RealEngine(Engine):
    """FlagEmbedding BGEM3FlagModel(CPU) 기반 실 엔진.

    FlagEmbedding/torch는 'models' extra로만 설치된다. 최상단 import 대신
    생성 시점에 lazy-import 하여, 미설치 환경에서도 모듈 import는 성공하게 한다.

    dense(CLS pooling)만 쓰므로 BGE-M3 파인튜닝 모델(KURE-v1 등)은 colbert/sparse 가중치
    파일이 없어도 그대로 로딩된다 (FlagEmbedding 이 "new initialize" 경고만 남김 — dense 무관).
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.model_name = settings.model_name
        self.dim = EMBEDDING_DIM
        self._max_batch = settings.embedding_max_batch
        self._max_length = settings.embedding_max_length
        try:
            from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415 (lazy)
        except ImportError as exc:  # pragma: no cover - 로컬엔 미설치
            raise RuntimeError(
                "FlagEmbedding 미설치. 'models' extra 설치 또는 EMBEDDING_MOCK=1 사용."
            ) from exc
        # 로컬 경로 로딩만 (§3.4). Hub ID 금지.
        self._model = BGEM3FlagModel(settings.embedding_model_path, use_fp16=False)

    def _encode(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        out: list[list[float]] = []
        for chunk in batched(texts, self._max_batch):
            encoded = self._model.encode(
                list(chunk),
                max_length=self._max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = np.asarray(encoded["dense_vecs"], dtype=np.float64)
            if normalize:
                dense = _l2_normalize(dense)
            out.extend(dense.tolist())
        return out


def build_engine(settings: Settings) -> Engine:
    """설정에 따라 엔진 선택. mock=on 또는 모델 경로 부재 → MockEngine."""
    import os

    use_mock = settings.embedding_mock or not os.path.isdir(settings.embedding_model_path)
    if use_mock:
        return MockEngine(settings)
    return RealEngine(settings)

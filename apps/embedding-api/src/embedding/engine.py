"""임베딩 엔진 추상화 — docs/TDD.md §7.3.

- Mock 활성화(EMBEDDING_MOCK) 또는 모델 경로 부재 → MockEngine (결정론적).
- 그 외 → RealEngine: FlagEmbedding을 __init__ 시점에 lazy-import.
  (로컬 Intel macOS엔 FlagEmbedding/torch 미설치 — import 시점에 실패하면 안 되므로
   모듈 최상단이 아니라 엔진 생성 시점에만 import 한다.)
- dim은 BGE-M3 고정 1024.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from itertools import batched

import numpy as np

from embedding.core.config import Settings

EMBEDDING_DIM = 1024


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class Engine(ABC):
    """임베딩 엔진 인터페이스."""

    model_name: str
    dim: int = EMBEDDING_DIM

    @abstractmethod
    def embed(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        """텍스트 리스트 → dense 벡터 리스트."""
        raise NotImplementedError


class MockEngine(Engine):
    """결정론적 mock 엔진. 동일 텍스트 → 동일 벡터 (테스트/로컬용)."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = f"{settings.model_name}-mock"
        self.dim = EMBEDDING_DIM

    @staticmethod
    def _seed(text: str) -> int:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _vector(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(self._seed(text))
        return rng.standard_normal(EMBEDDING_DIM).astype(np.float64)

    def embed(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        if not texts:
            return []
        vectors = np.stack([self._vector(t) for t in texts])
        if normalize:
            vectors = _l2_normalize(vectors)
        return vectors.tolist()


class RealEngine(Engine):
    """FlagEmbedding BGEM3FlagModel(CPU) 기반 실 엔진.

    FlagEmbedding/torch는 'models' extra로만 설치된다. 최상단 import 대신
    생성 시점에 lazy-import 하여, 미설치 환경에서도 모듈 import는 성공하게 한다.
    """

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.model_name
        self.dim = EMBEDDING_DIM
        self._max_batch = settings.embedding_max_batch
        try:
            from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415 (lazy)
        except ImportError as exc:  # pragma: no cover - 로컬엔 미설치
            raise RuntimeError(
                "FlagEmbedding 미설치. 'models' extra 설치 또는 EMBEDDING_MOCK=1 사용."
            ) from exc
        # 로컬 경로 로딩만 (§3.4). Hub ID 금지.
        self._model = BGEM3FlagModel(settings.embedding_model_path, use_fp16=False)

    def embed(self, texts: list[str], *, normalize: bool) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for chunk in batched(texts, self._max_batch):
            encoded = self._model.encode(
                list(chunk),
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

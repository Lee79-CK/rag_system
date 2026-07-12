"""재정렬 엔진 추상화 — docs/TDD.md §7.4.

- Mock 활성화(RERANKER_MOCK) 또는 모델 경로 부재 → MockEngine (결정론적 어휘 중첩 점수).
- 그 외 → RealEngine: FlagEmbedding FlagReranker 를 __init__ 시점에 lazy-import.
- score 는 sigmoid 정규화 (0,1) — threshold 비교 일관성 (§7.4).
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from reranker.core.config import Settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


@dataclass(frozen=True)
class RerankResult:
    index: int  # 원본 documents 리스트에서의 위치
    score: float


class Engine(ABC):
    """재정렬 엔진 인터페이스."""

    model_name: str

    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        """score 내림차순 정렬 후 상위 top_n (원본 인덱스 유지)."""
        raise NotImplementedError

    @staticmethod
    def _top_n(scored: list[RerankResult], top_n: int) -> list[RerankResult]:
        # score 내림차순; 동점은 원본 인덱스 오름차순으로 안정 정렬.
        ordered = sorted(scored, key=lambda r: (-r.score, r.index))
        if top_n is not None and top_n >= 0:
            return ordered[:top_n]
        return ordered


class MockEngine(Engine):
    """결정론적 어휘 중첩(Jaccard) 기반 mock 엔진."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = f"{settings.model_name}-mock"

    @staticmethod
    def _score(query_tokens: set[str], doc: str) -> float:
        doc_tokens = _tokenize(doc)
        if not query_tokens or not doc_tokens:
            return _sigmoid(0.0)
        inter = len(query_tokens & doc_tokens)
        union = len(query_tokens | doc_tokens)
        jaccard = inter / union if union else 0.0
        # (0,1) Jaccard 를 [-6, 6] 로직트로 스케일 → sigmoid 로 (0,1) 정규화.
        return _sigmoid((jaccard * 2.0 - 1.0) * 6.0)

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        q = _tokenize(query)
        scored = [RerankResult(index=i, score=self._score(q, d)) for i, d in enumerate(documents)]
        return self._top_n(scored, top_n)


class RealEngine(Engine):
    """FlagEmbedding FlagReranker(CPU) 기반 실 엔진 (lazy-import)."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.model_name
        self._max_length = settings.reranker_max_length
        try:
            from FlagEmbedding import FlagReranker  # noqa: PLC0415 (lazy)
        except ImportError as exc:  # pragma: no cover - 로컬엔 미설치
            raise RuntimeError(
                "FlagEmbedding 미설치. 'models' extra 설치 또는 RERANKER_MOCK=1 사용."
            ) from exc
        # 로컬 경로 로딩만 (§3.4). Hub ID 금지.
        self._model = FlagReranker(settings.reranker_model_path, use_fp16=False)

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[RerankResult]:
        if not documents:
            return []
        pairs = [[query, d] for d in documents]
        raw = self._model.compute_score(pairs, max_length=self._max_length, normalize=True)
        if not isinstance(raw, list):
            raw = [raw]
        scored = [RerankResult(index=i, score=float(s)) for i, s in enumerate(raw)]
        return self._top_n(scored, top_n)


def build_engine(settings: Settings) -> Engine:
    """설정에 따라 엔진 선택. mock=on 또는 모델 경로 부재 → MockEngine."""
    import os

    use_mock = settings.reranker_mock or not os.path.isdir(settings.reranker_model_path)
    if use_mock:
        return MockEngine(settings)
    return RealEngine(settings)

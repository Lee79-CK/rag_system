"""토큰 카운팅 (§7.2.2).

MUST(운영): vLLM 모델 tokenizer를 로컬 경로에서 로딩해 계산 (TOKENIZER_PATH).
로컬/모델 미배치 시: 문자수 기반 heuristic fallback (transformers 미설치여도 동작).
"""

from __future__ import annotations

import math
from typing import Protocol


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class HeuristicTokenCounter:
    """한국어/혼합 텍스트 근사 — 평균 ~3 chars/token. 결정론적, 의존성 없음."""

    def __init__(self, chars_per_token: float = 3.0) -> None:
        self._cpt = chars_per_token

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self._cpt))


class HFTokenCounter:
    """transformers AutoTokenizer 로컬 경로 로딩. 미설치/미배치 시 생성 실패 → fallback."""

    def __init__(self, tokenizer_path: str) -> None:
        from transformers import AutoTokenizer  # lazy: 폐쇄망/로컬 선택 로딩

        self._tok = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)

    def count(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False))


def make_token_counter(tokenizer_path: str | None) -> TokenCounter:
    """모델 경로가 로딩 가능하면 HF, 아니면 heuristic."""
    if tokenizer_path:
        try:
            return HFTokenCounter(tokenizer_path)
        except Exception:  # noqa: BLE001 — 로컬/폐쇄망 미배치 시 조용히 fallback
            pass
    return HeuristicTokenCounter()

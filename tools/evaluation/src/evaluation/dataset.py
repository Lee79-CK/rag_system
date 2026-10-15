"""평가 데이터셋 로더 — tests/evaluation/dataset/*.yaml (§13.3).

파일 하나에 문항 1개(mapping) 또는 여러 개(list — RAG Admin 품질 평가 "내보내기" 형식)를 둘 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from evaluation.models import EvalCase


def load_dataset(directory: str | Path) -> list[EvalCase]:
    path = Path(directory)
    cases: list[EvalCase] = []
    for yml in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(yml.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else [raw]
        cases.extend(EvalCase.model_validate(item) for item in items)
    return cases

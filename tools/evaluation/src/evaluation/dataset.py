"""평가 데이터셋 로더 — tests/evaluation/dataset/*.yaml (§13.3)."""

from __future__ import annotations

from pathlib import Path

import yaml

from evaluation.models import EvalCase


def load_dataset(directory: str | Path) -> list[EvalCase]:
    path = Path(directory)
    cases: list[EvalCase] = []
    for yml in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(yml.read_text(encoding="utf-8"))
        cases.append(EvalCase.model_validate(raw))
    return cases

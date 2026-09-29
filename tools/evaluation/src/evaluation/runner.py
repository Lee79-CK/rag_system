"""평가 Runner CLI (§8.2, §13.3).

`python -m evaluation.runner --dataset tests/evaluation/dataset [--out reports/eval.md]`
rag-api의 동기 completions 엔드포인트(§9)에 질의하여 지표를 산출한다.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx

from evaluation.dataset import load_dataset
from evaluation.metrics import summarize
from evaluation.models import CaseResult, EvalCase, RetrievedDoc
from evaluation.report import render_report


def run_case(client: httpx.Client, rag_url: str, case: EvalCase) -> CaseResult:
    try:
        resp = client.post(
            f"{rag_url.rstrip('/')}/internal/v1/rag/completions",
            json={
                "channel_id": case.channel_id,
                "message": case.question,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — 개별 실패는 리포트에 기록하고 계속
        return CaseResult(case=case, answer="", insufficient_evidence=False, error=str(exc)[:200])

    citations = [
        RetrievedDoc(document_name=c["document_name"], page=c.get("page"))
        for c in data.get("citations", [])
    ]
    return CaseResult(
        case=case,
        answer=data.get("answer", ""),
        insufficient_evidence=data.get("insufficient_evidence", False),
        # 동기 엔드포인트는 사용된 citation만 반환 → retrieved 근사치로 사용 (§9 한계)
        retrieved=citations,
        citations=citations,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 품질 평가 runner")
    parser.add_argument("--dataset", default="tests/evaluation/dataset")
    parser.add_argument("--out", default="reports/evaluation_report.md")
    parser.add_argument("--type", default=None, help="특정 유형만 평가")
    parser.add_argument("--rag-url", default=os.environ.get("RAG_API_URL", "http://localhost:8002"))
    args = parser.parse_args()

    cases = load_dataset(args.dataset)
    if args.type:
        cases = [c for c in cases if c.type == args.type]

    results: list[CaseResult] = []
    with httpx.Client(
        timeout=httpx.Timeout(connect=3.0, read=120.0, write=10.0, pool=10.0)
    ) as client:
        for case in cases:
            results.append(run_case(client, args.rag_url, case))

    summary = summarize(results)
    report = render_report(summary, results)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n[report] {out}")


if __name__ == "__main__":
    main()

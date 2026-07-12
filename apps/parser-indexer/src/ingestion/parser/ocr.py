"""OCR — 플래그 게이트 스텁 (docs/TDD.md §7.7, DEC-005 기본 비활성).

(v1.2) OCR 격리 fallback: `paddlepaddle` cp312 휠 부재 시 OCR 단계는 별도
Python 3.11 `ocr-worker` 이미지로 분리한다. parser-indexer 본체(3.12)에서는
OCR을 실행하지 않으며, `OCR_ENABLED=false`가 기본이므로 PoC를 차단하지 않는다.

이 모듈은 OCR이 활성일 때의 진입점만 정의한다. 실제 PaddleOCR 실행은
`ocr` optional-dependency가 설치된 별도 이미지에서만 동작한다.
"""

from __future__ import annotations

from pathlib import Path

from rag_schemas import ParsedDocument

from ingestion.parser.errors import ParseFailed


def run_ocr(path: str | Path, *, document_id: str, version_id: str) -> ParsedDocument:
    """OCR 실행 진입점. 기본 빌드에는 PaddleOCR가 없어 항상 실패한다.

    OCR을 사용하려면 `ocr` extra가 설치된 별도 이미지에서 실행하고 이 함수를
    구현체로 교체한다 (§7.7 OCR 격리 fallback).
    """
    p = Path(path)
    try:
        import paddleocr  # noqa: F401
    except ImportError as exc:
        raise ParseFailed(
            f"OCR 활성화되었으나 PaddleOCR 미설치(격리 ocr-worker 필요): {p.name}",
            code="OCR_UNAVAILABLE",
        ) from exc

    # 실제 OCR 파이프라인은 격리 ocr-worker(Python 3.11)에서 구현한다.
    raise ParseFailed(
        f"OCR 실행 경로는 격리 ocr-worker에서만 지원: {p.name}",
        code="OCR_NOT_IMPLEMENTED",
    )

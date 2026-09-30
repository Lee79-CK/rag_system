"""PDF 파서 — PyMuPDF 기본 + pdfplumber 보완 (docs/TDD.md §7.7 step 2, 가이드 §5.1.2).

- 텍스트/페이지 추출: PyMuPDF span 단위 (폰트명으로 Wingdings 글머리표 복원 — korean_text.repair_span)
- 추출 순서가 깨진 페이지(MS Print-To-PDF 류, 구두점이 독립 줄로 떨어짐) → 그 페이지만
  pdfplumber 글자 좌표 정렬 텍스트로 대체 (PDF_TEXT_ENGINE=auto). pdfplumber 는 ~90배 느려 전 페이지 적용하지 않는다.
- 한글 정규화(NFC·가운뎃점/괄호 통일·깨진 매핑 보정) + 반복 머리말/꼬리말·쪽 번호 제거
- 표 감지 페이지: pdfplumber로 표 추출 → ParsedElement(type="Table", Markdown)
- 텍스트 비율 < 5% & OCR 비활성 → ParseFailed(code="SCANNED_NO_OCR")
- 텍스트 레이어가 거의 없고 이미지가 있는 페이지(도표·흐름도·표지)는 stats.image_only_pages 로 보고
  (OCR 없이는 그 페이지 내용이 색인되지 않는다)
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF
import pdfplumber
from rag_observability import get_logger
from rag_schemas import ParsedDocument, ParsedElement, ParsedPage

from ingestion.parser.errors import ParseFailed
from ingestion.parser.korean_text import (
    is_scrambled,
    normalize_text,
    repair_span,
    strip_headers_footers,
)

logger = get_logger(__name__)

PdfTextEngine = Literal["auto", "pymupdf", "pdfplumber"]

# 텍스트 비율이 이 값 미만이면 스캔 문서로 간주 (§7.7 step 2).
_TEXT_RATIO_THRESHOLD = 0.05
# 이 문자 수 미만 + 이미지 보유 페이지 = 이미지 전용 페이지 (텍스트가 그림 안에만 있다).
_IMAGE_ONLY_MAX_CHARS = 100


def _rows_to_markdown(rows: list[list[str | None]]) -> str:
    """표(행 리스트)를 Markdown 표 문자열로 변환한다 (§19.1)."""
    norm = [
        [("" if c is None else normalize_text(str(c).replace("\n", " "))[0]) for c in row]
        for row in rows
    ]
    norm = [r for r in norm if any(cell for cell in r)]
    if not norm:
        return ""
    width = max(len(r) for r in norm)
    norm = [r + [""] * (width - len(r)) for r in norm]
    header = norm[0]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in norm[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _page_text_pymupdf(page: fitz.Page) -> tuple[str, int]:
    """span 단위로 텍스트를 조립한다 (get_text("text") 와 같은 줄 구성 + 폰트 기반 글머리표 복원)."""
    lines: list[str] = []
    repaired = 0
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 0=text, 1=image
            continue
        for line in block["lines"]:
            parts: list[str] = []
            for span in line["spans"]:
                text, n = repair_span(span["text"], span.get("font"))
                parts.append(text)
                repaired += n
            lines.append("".join(parts))
    return "\n".join(lines), repaired


def _plumber_pass(
    pdf_path: Path, text_pages: set[int]
) -> tuple[dict[int, list[str]], dict[int, str]]:
    """pdfplumber 1회 순회: 전 페이지 표 Markdown + `text_pages` 페이지의 좌표 정렬 텍스트.

    반환: (1-based page → [표 md, ...], 1-based page → 텍스트)
    """
    tables_by_page: dict[int, list[str]] = {}
    texts_by_page: dict[int, str] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                if idx in text_pages:
                    # 대체 실패 시 PyMuPDF 텍스트 유지
                    with contextlib.suppress(Exception):
                        texts_by_page[idx] = page.extract_text() or ""
                try:
                    extracted = page.extract_tables()
                except Exception:  # noqa: BLE001
                    continue
                mds = [md for tbl in extracted if (md := _rows_to_markdown(tbl))]
                if mds:
                    tables_by_page[idx] = mds
    except Exception:  # noqa: BLE001
        # 표/대체 추출은 보완 단계 — 실패해도 본문 파싱을 막지 않는다.
        return {}, {}
    return tables_by_page, texts_by_page


def parse_pdf(
    path: str | Path,
    *,
    document_id: str,
    version_id: str,
    ocr_enabled: bool = False,
    text_engine: PdfTextEngine = "auto",
) -> ParsedDocument:
    p = Path(path)
    try:
        doc = fitz.open(str(p))
    except Exception as exc:  # noqa: BLE001
        raise ParseFailed(f"PDF 열기 실패: {p.name}", code="CORRUPT") from exc

    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise ParseFailed(f"암호화된 PDF: {p.name}", code="ENCRYPTED")

    try:
        page_texts: list[str] = []
        page_images: list[int] = []
        repaired = 0
        for page in doc:
            text, n = _page_text_pymupdf(page)
            page_texts.append(text)
            page_images.append(len(page.get_images()))
            repaired += n
        page_count = len(page_texts)
    finally:
        doc.close()

    total_chars = sum(len(t.strip()) for t in page_texts)
    # 텍스트 비율 근사: 페이지당 기대 문자수 대비 실제 추출 문자수.
    # 스캔 PDF는 페이지가 있어도 추출 텍스트가 거의 0에 수렴한다.
    expected = max(page_count, 1) * 500  # 페이지당 최소 기대 문자수(근사)
    text_ratio = total_chars / expected

    if page_count > 0 and text_ratio < _TEXT_RATIO_THRESHOLD:
        if not ocr_enabled:
            raise ParseFailed(f"스캔 문서로 추정되나 OCR 비활성: {p.name}", code="SCANNED_NO_OCR")
        from ingestion.parser.ocr import run_ocr

        return run_ocr(p, document_id=document_id, version_id=version_id)

    # 페이지별 텍스트 엔진 선택 (1-based).
    if text_engine == "pdfplumber":
        plumber_pages = set(range(1, page_count + 1))
    elif text_engine == "pymupdf":
        plumber_pages = set()
    else:
        plumber_pages = {i for i, t in enumerate(page_texts, start=1) if is_scrambled(t)}

    tables_by_page, plumber_texts = _plumber_pass(p, plumber_pages)
    for i, text in plumber_texts.items():
        page_texts[i - 1] = text

    normalized: list[str] = []
    for text in page_texts:
        norm, n = normalize_text(text)
        normalized.append(norm)
        repaired += n
    cleaned, removed_lines = strip_headers_footers(normalized)

    pages: list[ParsedPage] = []
    table_count = 0
    image_only_pages: list[int] = []
    for i, text in enumerate(cleaned, start=1):
        elements: list[ParsedElement] = []
        body = text.strip()
        if len(body) < _IMAGE_ONLY_MAX_CHARS and page_images[i - 1] > 0:
            image_only_pages.append(i)
        if body:
            elements.append(ParsedElement(type="NarrativeText", text=body, metadata={"page": i}))
        for md in tables_by_page.get(i, []):
            table_count += 1
            elements.append(ParsedElement(type="Table", text=md, metadata={"page": i}))
        pages.append(ParsedPage(page=i, elements=elements))

    final_chars = sum(len(t.strip()) for t in cleaned)
    if final_chars == 0 and table_count == 0:
        raise ParseFailed(f"추출 텍스트 없음: {p.name}", code="EMPTY")

    if image_only_pages:
        logger.warning(
            "pdf_image_only_pages",
            file=p.name,
            count=len(image_only_pages),
            pages=image_only_pages[:50],
            hint="도표/흐름도 내 텍스트는 OCR 없이 색인되지 않음",
        )

    return ParsedDocument(
        document_id=document_id,
        version_id=version_id,
        parser="pymupdf+pdfplumber" if plumber_texts else "pymupdf",
        pages=pages,
        stats={
            "page_count": page_count,
            "char_count": final_chars,
            "table_count": table_count,
            "image_count": sum(page_images),
            "pdfplumber_text_pages": sorted(plumber_texts),
            "repaired_glyphs": repaired,
            "header_footer_lines_removed": removed_lines,
            "image_only_pages": image_only_pages,
        },
    )

"""PDF 파서 — PyMuPDF 기본 + pdfplumber 표 보완 (docs/TDD.md §7.7 step 2).

- 텍스트/페이지 추출: PyMuPDF (fitz)
- 표 감지 페이지: pdfplumber로 표 추출 → ParsedElement(type="Table", Markdown)
- 텍스트 비율 < 5% & OCR 비활성 → ParseFailed(code="SCANNED_NO_OCR")
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
from rag_schemas import ParsedDocument, ParsedElement, ParsedPage

from ingestion.parser.errors import ParseFailed

# 텍스트 비율이 이 값 미만이면 스캔 문서로 간주 (§7.7 step 2).
_TEXT_RATIO_THRESHOLD = 0.05


def _rows_to_markdown(rows: list[list[str | None]]) -> str:
    """표(행 리스트)를 Markdown 표 문자열로 변환한다 (§19.1)."""
    norm = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in row] for row in rows]
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


def _extract_tables(pdf_path: Path) -> dict[int, list[str]]:
    """pdfplumber로 페이지별 표 Markdown 목록을 추출한다. (1-based page → [md, ...])"""
    tables_by_page: dict[int, list[str]] = {}
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                extracted = page.extract_tables()
                if not extracted:
                    continue
                mds = [md for tbl in extracted if (md := _rows_to_markdown(tbl))]
                if mds:
                    tables_by_page[idx] = mds
    except Exception:  # noqa: BLE001
        # 표 추출은 보완 단계 — 실패해도 본문 파싱을 막지 않는다.
        return {}
    return tables_by_page


def parse_pdf(
    path: str | Path,
    *,
    document_id: str,
    version_id: str,
    ocr_enabled: bool = False,
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
        image_count = 0
        for page in doc:
            page_texts.append(page.get_text("text"))
            image_count += len(page.get_images())
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

    tables_by_page = _extract_tables(p)

    pages: list[ParsedPage] = []
    table_count = 0
    for i, text in enumerate(page_texts, start=1):
        elements: list[ParsedElement] = []
        body = text.strip()
        if body:
            elements.append(ParsedElement(type="NarrativeText", text=body, metadata={"page": i}))
        for md in tables_by_page.get(i, []):
            table_count += 1
            elements.append(ParsedElement(type="Table", text=md, metadata={"page": i}))
        pages.append(ParsedPage(page=i, elements=elements))

    if total_chars == 0 and table_count == 0:
        raise ParseFailed(f"추출 텍스트 없음: {p.name}", code="EMPTY")

    return ParsedDocument(
        document_id=document_id,
        version_id=version_id,
        parser="pymupdf",
        pages=pages,
        stats={
            "page_count": page_count,
            "char_count": total_chars,
            "table_count": table_count,
            "image_count": image_count,
        },
    )

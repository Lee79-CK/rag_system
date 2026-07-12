"""Parser Dispatcher — 확장자 → Parser Strategy 라우팅 (docs/TDD.md §7.7 step 2)."""

from __future__ import annotations

from pathlib import Path

from rag_schemas import ParsedDocument

from ingestion.parser.errors import ParseFailed
from ingestion.parser.office_parser import parse_docx, parse_pptx, parse_xlsx
from ingestion.parser.pdf_parser import parse_pdf
from ingestion.parser.text_parser import parse_html, parse_text

# 지원 확장자 목록 — 검증/에러 메시지에 사용.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
}


def parse_document(
    path: str | Path,
    *,
    document_id: str,
    version_id: str,
    ocr_enabled: bool = False,
) -> ParsedDocument:
    """파일 확장자로 파서를 선택하여 ParsedDocument를 반환한다.

    지원하지 않는 확장자는 ParseFailed(code="UNSUPPORTED_TYPE").
    """
    p = Path(path)
    ext = p.suffix.lower()

    match ext:
        case ".pdf":
            return parse_pdf(
                p, document_id=document_id, version_id=version_id, ocr_enabled=ocr_enabled
            )
        case ".docx":
            return parse_docx(p, document_id=document_id, version_id=version_id)
        case ".pptx":
            return parse_pptx(p, document_id=document_id, version_id=version_id)
        case ".xlsx":
            return parse_xlsx(p, document_id=document_id, version_id=version_id)
        case ".txt" | ".md" | ".markdown":
            return parse_text(p, document_id=document_id, version_id=version_id)
        case ".html" | ".htm":
            return parse_html(p, document_id=document_id, version_id=version_id)
        case _:
            raise ParseFailed(
                f"지원하지 않는 확장자: {ext or '(없음)'} — {p.name}",
                code="UNSUPPORTED_TYPE",
            )

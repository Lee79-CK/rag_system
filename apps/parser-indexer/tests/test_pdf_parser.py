"""PDF 파서 테스트 — PyMuPDF 로 생성한 한글 PDF (FR-PARSER-002/003/008, 가이드 §5.1.2).

내장 CJK 폰트(fontname="korea")로 텍스트 레이어를 만든다. 외부 파일/네트워크 불필요.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from ingestion.parser.errors import ParseFailed
from ingestion.parser.pdf_parser import parse_pdf

_FONT = "korea"
_BODY = [
    "인공지능사업자는 위험평가 결과를 바탕으로 위험을 완화하기 위한 조치를 수립 및 시행하여야 한다.",
    "위험완화조치의 시급성 및 효과, 비용·인력·기술적 한계 등 실행가능성을 고려하여야 한다.",
    "위험완화조치 이후 위험평가를 재실시하여 그 효과를 확인해야 하며 필요한 경우 수정·보완한다.",
]


def _normal_pdf(path: Path, pages: int = 4) -> Path:
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 40), "인공지능 안정성 확보 가이드라인", fontname=_FONT, fontsize=9)
        y = 100
        for line in _BODY:
            page.insert_text((72, y), f"{i}장 {line}", fontname=_FONT, fontsize=10)
            y += 20
        page.insert_text((290, 800), f"- {i} -", fontname=_FONT, fontsize=9)
    doc.save(str(path))
    return path


def _scrambled_pdf(path: Path) -> Path:
    """Print-To-PDF 처럼 구두점을 앞 글자보다 먼저·왼쪽에 그려 content stream 순서를 깨뜨린다."""
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in _BODY * 2:
        head, tail = line[:20], line[20:]
        page.insert_text((72, y), head, fontname=_FONT, fontsize=10)
        page.insert_text((60, y), ",", fontname=_FONT, fontsize=10)
        page.insert_text((72 + 10 * len(head), y), tail, fontname=_FONT, fontsize=10)
        y += 20
    doc.save(str(path))
    return path


def test_fr_parser_002_header_footer_and_page_numbers_removed(tmp_path: Path) -> None:
    doc = parse_pdf(_normal_pdf(tmp_path / "a.pdf"), document_id="d", version_id="v")
    text = doc.pages[0].elements[0].text
    assert "안정성 확보 가이드라인" not in text
    assert "- 1 -" not in text
    assert text.startswith("1장 인공지능사업자는")
    assert doc.stats["header_footer_lines_removed"] == 8
    assert doc.parser == "pymupdf"
    assert doc.stats["pdfplumber_text_pages"] == []


def test_fr_parser_003_scrambled_page_falls_back_to_pdfplumber(tmp_path: Path) -> None:
    path = _scrambled_pdf(tmp_path / "s.pdf")
    # PyMuPDF 단독 추출은 구두점이 독립 줄로 떨어진다 (전제 확인)
    raw = fitz.open(str(path))[0].get_text()
    assert "\n,\n" in raw

    doc = parse_pdf(path, document_id="d", version_id="v")
    assert doc.parser == "pymupdf+pdfplumber"
    assert doc.stats["pdfplumber_text_pages"] == [1]
    lines = doc.pages[0].elements[0].text.split("\n")
    assert "," not in lines
    assert any("인공지능사업자는" in ln and "조치를" in ln for ln in lines)


def test_fr_parser_003_text_engine_pymupdf_disables_fallback(tmp_path: Path) -> None:
    doc = parse_pdf(
        _scrambled_pdf(tmp_path / "s.pdf"), document_id="d", version_id="v", text_engine="pymupdf"
    )
    assert doc.parser == "pymupdf"
    assert doc.stats["pdfplumber_text_pages"] == []


def test_fr_parser_008_image_only_page_reported(tmp_path: Path) -> None:
    path = _normal_pdf(tmp_path / "img.pdf", pages=3)
    doc = fitz.open(str(path))
    page = doc.new_page()  # 4쪽: 텍스트 없이 그림만 (흐름도 이미지 페이지)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    out = tmp_path / "img2.pdf"
    doc.save(str(out))

    parsed = parse_pdf(out, document_id="d", version_id="v")
    assert parsed.stats["image_only_pages"] == [4]
    assert parsed.stats["page_count"] == 4
    assert parsed.pages[3].elements == []


def test_fr_parser_004_scanned_pdf_without_ocr_fails(tmp_path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    with pytest.raises(ParseFailed) as exc:
        parse_pdf(path, document_id="d", version_id="v")
    assert exc.value.code == "SCANNED_NO_OCR"

"""Office 파서 테스트 — xlsx → Markdown (docs/TDD.md §7.7 step 2)."""

from __future__ import annotations

from ingestion.parser.office_parser import parse_xlsx
from openpyxl import Workbook


def test_office_xlsx_to_markdown(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "직원"
    ws.append(["이름", "부서"])
    ws.append(["홍길동", "인사"])
    ws.append(["김철수", "개발"])
    xlsx = tmp_path / "employees.xlsx"
    wb.save(xlsx)

    doc = parse_xlsx(xlsx, document_id="d", version_id="v")
    assert doc.parser == "openpyxl"

    table_elements = [el for page in doc.pages for el in page.elements if el.type == "Table"]
    assert len(table_elements) == 1
    md = table_elements[0].text
    # Markdown 표 구조
    assert "| 이름 | 부서 |" in md
    assert "| --- | --- |" in md
    assert "| 홍길동 | 인사 |" in md
    assert "| 김철수 | 개발 |" in md

    # 시트명 Title 프리픽스
    titles = [el.text for page in doc.pages for el in page.elements if el.type == "Title"]
    assert "[시트] 직원" in titles
    assert doc.stats["table_count"] == 1

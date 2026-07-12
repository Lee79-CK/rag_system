"""text/html 파서 단위 테스트 (docs/TDD.md §7.7)."""

from __future__ import annotations

from ingestion.parser.text_parser import parse_html, parse_text


def test_text_parser_txt_and_md(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("첫 줄입니다.\n둘째 줄.", encoding="utf-8")
    md = tmp_path / "b.md"
    md.write_text("# 제목\n\n본문 내용.", encoding="utf-8")

    doc_txt = parse_text(txt, document_id="doc1", version_id="v1")
    assert doc_txt.parser == "text"
    assert doc_txt.document_id == "doc1"
    assert doc_txt.version_id == "v1"
    assert len(doc_txt.pages) == 1
    assert "첫 줄입니다." in doc_txt.pages[0].elements[0].text
    assert doc_txt.stats["char_count"] > 0

    doc_md = parse_text(md, document_id="doc1", version_id="v1")
    assert "# 제목" in doc_md.pages[0].elements[0].text
    assert "본문 내용." in doc_md.pages[0].elements[0].text


def test_html_parser_strips_tags(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(
        """
        <html><head><title>제목입니다</title>
        <style>.x{color:red}</style>
        <script>alert('x')</script></head>
        <body><h1>머리말</h1><p>본문 <b>강조</b> 텍스트</p></body></html>
        """,
        encoding="utf-8",
    )
    doc = parse_html(html, document_id="d", version_id="v")
    text = doc.pages[0].elements[0].text
    assert "머리말" in text
    assert "본문" in text
    assert "강조" in text
    # script/style 내용은 제거되어야 한다.
    assert "alert" not in text
    assert "color:red" not in text
    assert "<p>" not in text and "<script>" not in text
    assert doc.pages[0].elements[0].metadata["title"] == "제목입니다"

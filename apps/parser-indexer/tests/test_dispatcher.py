"""Dispatcher 라우팅 테스트 (docs/TDD.md §7.7 step 2)."""

from __future__ import annotations

import pytest
from ingestion.parser.dispatcher import parse_document
from ingestion.parser.errors import ParseFailed


def test_dispatcher_routes_by_extension(tmp_path):
    txt = tmp_path / "note.txt"
    txt.write_text("텍스트 문서 본문.", encoding="utf-8")
    doc = parse_document(txt, document_id="d", version_id="v")
    assert doc.parser == "text"

    html = tmp_path / "p.html"
    html.write_text("<html><body><p>웹 문서</p></body></html>", encoding="utf-8")
    doc_html = parse_document(html, document_id="d", version_id="v")
    assert doc_html.parser == "html"
    assert "웹 문서" in doc_html.pages[0].elements[0].text


def test_dispatcher_unsupported_extension_raises(tmp_path):
    weird = tmp_path / "data.xyz"
    weird.write_text("x", encoding="utf-8")
    with pytest.raises(ParseFailed) as exc:
        parse_document(weird, document_id="d", version_id="v")
    assert exc.value.code == "UNSUPPORTED_TYPE"

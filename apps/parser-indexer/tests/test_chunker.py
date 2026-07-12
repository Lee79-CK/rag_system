"""Chunker 테스트 (docs/TDD.md §7.7 step 4, §19.1)."""

from __future__ import annotations

from ingestion.chunker.chunker import chunk_document
from rag_schemas import ParsedDocument, ParsedElement, ParsedPage


def _long_doc() -> ParsedDocument:
    body = "가나다라마바사아자차카타파하 " * 400  # 충분히 길게
    return ParsedDocument(
        document_id="doc-1",
        version_id="ver-9",
        parser="text",
        pages=[
            ParsedPage(
                page=1,
                elements=[
                    ParsedElement(type="Title", text="섹션 제목"),
                    ParsedElement(type="NarrativeText", text=body),
                ],
            )
        ],
    )


def test_chunker_splits_and_prefixes():
    chunks = chunk_document(
        _long_doc(),
        chunk_size_tokens=100,
        chunk_overlap_tokens=20,
        chars_per_token=3.3,
        min_chunk_tokens=10,
        default_title="문서 제목",
    )
    # 긴 텍스트 → 여러 chunk
    assert len(chunks) > 1

    # chunk_id 포맷: f"{version_id}-{index:05d}"
    assert chunks[0].chunk_id == "ver-9-00000"
    assert chunks[1].chunk_id == "ver-9-00001"

    # title/section prefix 부여
    assert chunks[0].text.startswith("문서 제목 > 섹션 제목")
    assert chunks[0].section == "섹션 제목"

    # 인덱스는 연속적이며 0-based
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunker_keeps_table_markdown_intact():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    doc = ParsedDocument(
        document_id="d",
        version_id="v",
        parser="text",
        pages=[
            ParsedPage(
                page=1,
                elements=[ParsedElement(type="Table", text=md)],
            )
        ],
    )
    chunks = chunk_document(doc, chunk_size_tokens=5, chunk_overlap_tokens=1, min_chunk_tokens=1)
    # 표는 분할되지 않고 통짜로 하나의 chunk 안에 유지된다.
    table_chunks = [c for c in chunks if c.is_table]
    assert len(table_chunks) == 1
    assert md in table_chunks[0].text

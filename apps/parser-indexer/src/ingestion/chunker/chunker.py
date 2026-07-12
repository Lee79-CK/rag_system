"""Chunking — RecursiveCharacterTextSplitter 기반 (docs/TDD.md §7.7 step 4, §19.1).

- chunk_size=800tok / overlap=120tok 목표. transformers tokenizer가 로컬에 없으므로
  문자를 토큰으로 근사한다 (chars ≈ tokens * chars_per_token). 표(Markdown)는 분할
  대상에서 제외하여 원형을 유지한다.
- 최소 ~50tok 미만 chunk는 이웃과 병합한다.
- 각 chunk에 title/section prefix를 부여한다.
- chunk_id = f"{version_id}-{chunk_index:05d}".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter
from rag_schemas import ParsedDocument


@dataclass
class Chunk:
    """색인 단위. 임베딩/upsert 단계로 전달된다."""

    chunk_id: str
    chunk_index: int
    text: str
    title: str
    section: str | None
    page_start: int | None
    page_end: int | None
    is_table: bool = False
    metadata: dict = field(default_factory=dict)


def _tokens_to_chars(tokens: int, factor: float) -> int:
    return max(1, int(round(tokens * factor)))


def _iter_blocks(doc: ParsedDocument) -> list[dict]:
    """ParsedDocument를 (텍스트 블록 + 위치/섹션) 리스트로 평탄화한다.

    Title 요소는 이후 블록들의 현재 섹션명으로 사용한다.
    Table 요소는 분할하지 않도록 `is_table=True`로 표시한다.
    """
    blocks: list[dict] = []
    current_section: str | None = None
    for page in doc.pages:
        for el in page.elements:
            text = el.text.strip()
            if not text:
                continue
            if el.type == "Title":
                current_section = text
            blocks.append(
                {
                    "text": text,
                    "type": el.type,
                    "page": page.page,
                    "section": current_section,
                    "is_table": el.type == "Table",
                }
            )
    return blocks


def chunk_document(
    doc: ParsedDocument,
    *,
    chunk_size_tokens: int = 800,
    chunk_overlap_tokens: int = 120,
    chars_per_token: float = 3.3,
    min_chunk_tokens: int = 50,
    default_title: str = "",
) -> list[Chunk]:
    """ParsedDocument → 색인용 Chunk 목록."""
    chunk_chars = _tokens_to_chars(chunk_size_tokens, chars_per_token)
    overlap_chars = _tokens_to_chars(chunk_overlap_tokens, chars_per_token)
    min_chars = _tokens_to_chars(min_chunk_tokens, chars_per_token)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_chars,
        chunk_overlap=overlap_chars,
        length_function=len,
        separators=["\n\n", "\n", "。", ". ", " ", ""],
    )

    title = default_title or (doc.stats.get("title") if isinstance(doc.stats, dict) else "") or ""

    # 1) 블록별로 조각 생성. 표는 통짜 유지.
    raw: list[dict] = []
    for block in _iter_blocks(doc):
        section = block["section"]
        page = block["page"]
        if block["is_table"]:
            raw.append(
                {
                    "text": block["text"],
                    "section": section,
                    "page_start": page,
                    "page_end": page,
                    "is_table": True,
                }
            )
            continue
        for piece in splitter.split_text(block["text"]):
            piece = piece.strip()
            if piece:
                raw.append(
                    {
                        "text": piece,
                        "section": section,
                        "page_start": page,
                        "page_end": page,
                        "is_table": False,
                    }
                )

    # 2) 최소 토큰 미만 조각을 이웃과 병합 (표는 병합 대상 제외).
    merged = _merge_small(raw, min_chars)

    # 3) title/section prefix 부여 + chunk_id 생성.
    chunks: list[Chunk] = []
    for idx, item in enumerate(merged):
        chunk_id = f"{doc.version_id}-{idx:05d}"
        prefix_parts = [part for part in (title, item.get("section")) if part]
        prefix = " > ".join(prefix_parts)
        body = item["text"]
        prefixed = f"{prefix}\n{body}" if prefix else body
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                chunk_index=idx,
                text=prefixed,
                title=title,
                section=item.get("section"),
                page_start=item.get("page_start"),
                page_end=item.get("page_end"),
                is_table=item.get("is_table", False),
                metadata={},
            )
        )
    return chunks


def _merge_small(raw: list[dict], min_chars: int) -> list[dict]:
    """min_chars 미만인 텍스트 조각을 이웃과 병합한다. 표 조각은 그대로 둔다."""
    if not raw:
        return []
    out: list[dict] = []
    for item in raw:
        if (
            not item["is_table"]
            and len(item["text"]) < min_chars
            and out
            and not out[-1]["is_table"]
        ):
            prev = out[-1]
            prev["text"] = f"{prev['text']}\n{item['text']}"
            prev["page_end"] = item["page_end"]
            if prev.get("section") is None:
                prev["section"] = item.get("section")
            continue
        out.append(dict(item))

    # 뒤로 병합할 이웃이 없어 첫 조각이 작을 수 있다 → 다음 텍스트 조각으로 흡수.
    if (
        len(out) >= 2
        and not out[0]["is_table"]
        and len(out[0]["text"]) < min_chars
        and not out[1]["is_table"]
    ):
        nxt = out[1]
        nxt["text"] = f"{out[0]['text']}\n{nxt['text']}"
        nxt["page_start"] = out[0]["page_start"]
        out.pop(0)
    return out

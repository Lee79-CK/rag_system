"""Document / Indexing 계층 스키마 — docs/TDD.md §4.4."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParsedElement(BaseModel):
    type: Literal["Title", "NarrativeText", "Table", "ListItem", "Image", "Other"]
    text: str
    metadata: dict = Field(default_factory=dict)


class ParsedPage(BaseModel):
    page: int
    elements: list[ParsedElement] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """PRD §18.5 표준 Schema."""

    document_id: str
    version_id: str
    parser: str
    pages: list[ParsedPage] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)  # page_count, char_count, table_count, image_count


class QdrantChunkPayload(BaseModel):
    """PRD §18.4와 필드 1:1. Qdrant point payload."""

    document_id: str
    document_version_id: str
    chunk_id: str  # f"{version_id}-{chunk_index:05d}"
    title: str
    source_file: str
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    chunk_index: int
    language: str = "ko"
    category: str | None = None
    department: str | None = None
    security_level: str = "INTERNAL"
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_channel_ids: list[str] = Field(default_factory=list)
    content_hash: str  # sha256
    is_active: bool = True
    text: str

"""txt/md/html 파서 (docs/TDD.md §7.7 step 2).

- .txt / .md : 그대로 통과 (NarrativeText)
- .html      : BeautifulSoup(lxml)로 script/style 제거 후 텍스트 정제
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from rag_schemas import ParsedDocument, ParsedElement, ParsedPage

from ingestion.parser.errors import ParseFailed


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 인코딩 폴백 — 폐쇄망 내부 문서 상당수가 cp949일 수 있다.
        try:
            return path.read_text(encoding="cp949")
        except Exception as exc:  # noqa: BLE001
            raise ParseFailed(f"텍스트 디코딩 실패: {path.name}", code="CORRUPT") from exc


def parse_text(path: str | Path, *, document_id: str, version_id: str) -> ParsedDocument:
    """txt/md 파일을 그대로 담은 ParsedDocument를 반환한다."""
    p = Path(path)
    text = _read_text(p).strip()
    if not text:
        raise ParseFailed(f"빈 문서: {p.name}", code="EMPTY")
    element = ParsedElement(type="NarrativeText", text=text, metadata={"source": p.name})
    page = ParsedPage(page=1, elements=[element])
    return ParsedDocument(
        document_id=document_id,
        version_id=version_id,
        parser="text",
        pages=[page],
        stats={"page_count": 1, "char_count": len(text), "table_count": 0, "image_count": 0},
    )


def parse_html(path: str | Path, *, document_id: str, version_id: str) -> ParsedDocument:
    """HTML을 BeautifulSoup(lxml)으로 정제하여 텍스트만 추출한다."""
    p = Path(path)
    raw = _read_text(p)
    soup = BeautifulSoup(raw, "lxml")

    # title은 head 제거 전에 추출한다.
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else p.stem

    for tag in soup(["script", "style", "head", "meta", "link", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    if not cleaned:
        raise ParseFailed(f"빈 HTML: {p.name}", code="EMPTY")

    element = ParsedElement(
        type="NarrativeText", text=cleaned, metadata={"source": p.name, "title": title}
    )
    page = ParsedPage(page=1, elements=[element])
    return ParsedDocument(
        document_id=document_id,
        version_id=version_id,
        parser="html",
        pages=[page],
        stats={"page_count": 1, "char_count": len(cleaned), "table_count": 0, "image_count": 0},
    )

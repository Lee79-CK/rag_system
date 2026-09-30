"""업로드 전 PDF 사전 점검 — 실제 parser-indexer 파서/청커로 돌려 본다 (rke2 가이드 §5.1.1/§5.1.2).

    uv run --package parser-indexer python scripts/inspect_pdf.py docs/pdf/*.pdf
    uv run --package parser-indexer python scripts/inspect_pdf.py manual.pdf --chars-per-token 1.9 --show 2

출력: 쪽수·문자수·pdfplumber 대체 쪽·글리프 보정 수·머리말/꼬리말 제거 줄·이미지 전용 쪽(OCR 없이 유실)·
청크 수/최대 길이·추정 토큰(한글 1.87자/토큰, bge-m3/KURE-v1 토크나이저 실측). 네트워크/DB 불필요.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ingestion.chunker.chunker import chunk_document
from ingestion.parser.errors import ParseFailed
from ingestion.parser.pdf_parser import parse_pdf

# bge-m3 / KURE-v1(XLM-R 토크나이저) 순수 한글 실측 — 가이드 §5.1.1
_KO_CHARS_PER_REAL_TOKEN = 1.87


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument(
        "--chars-per-token", type=float, default=1.9, help="CHARS_PER_TOKEN (values-lab 1.9)"
    )
    ap.add_argument("--chunk-size", type=int, default=800, help="CHUNK_SIZE (토큰)")
    ap.add_argument("--engine", default="auto", choices=["auto", "pymupdf", "pdfplumber"])
    ap.add_argument(
        "--max-length", type=int, default=2048, help="EMBEDDING_MAX_LENGTH (절단 경고용)"
    )
    ap.add_argument("--show", type=int, default=0, help="앞에서부터 N개 청크 본문 출력")
    args = ap.parse_args()

    rc = 0
    for path in args.pdfs:
        t0 = time.perf_counter()
        try:
            doc = parse_pdf(
                path, document_id="inspect", version_id="inspect", text_engine=args.engine
            )
        except ParseFailed as exc:
            print(f"✗ {path.name}: {exc}")
            rc = 1
            continue
        parse_s = time.perf_counter() - t0
        chunks = chunk_document(
            doc, chunk_size_tokens=args.chunk_size, chars_per_token=args.chars_per_token
        )
        st = doc.stats
        lengths = [len(c.text) for c in chunks] or [0]
        max_tok = max(lengths) / _KO_CHARS_PER_REAL_TOKEN
        over = sum(1 for n in lengths if n / _KO_CHARS_PER_REAL_TOKEN > args.max_length)
        print(f"■ {path.name}  ({doc.parser}, 파싱 {parse_s:.1f}s)")
        print(
            f"  {st['page_count']}쪽 · 텍스트 {st['char_count']:,}자 "
            f"({st['char_count'] / max(st['page_count'], 1):.0f}자/쪽) · 표 {st['table_count']}"
        )
        print(
            f"  pdfplumber 대체 {len(st['pdfplumber_text_pages'])}쪽 · 글리프 보정 {st['repaired_glyphs']} · "
            f"머리말/꼬리말 제거 {st['header_footer_lines_removed']}줄"
        )
        if st["image_only_pages"]:
            print(
                f"  ⚠ 이미지 전용 {len(st['image_only_pages'])}쪽 (OCR 없이 색인 안 됨 — 표지/흐름도 확인): "
                f"{st['image_only_pages'][:20]}"
            )
        print(
            f"  청크 {len(chunks)}개 (표 {sum(c.is_table for c in chunks)}) · 평균 "
            f"{sum(lengths) // len(lengths)}자 · 최대 {max(lengths)}자 ≈ {max_tok:.0f} tok(한글 기준)"
            + (f" · ⚠ {over}개가 EMBEDDING_MAX_LENGTH={args.max_length} 초과(절단)" if over else "")
        )
        for c in chunks[: args.show]:
            print(f"  --- chunk {c.chunk_index} (p{c.page_start}) ---")
            print("  " + c.text[:600].replace("\n", "\n  "))
    return rc


if __name__ == "__main__":
    sys.exit(main())

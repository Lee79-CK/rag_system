"""한글 PDF 텍스트 정규화 — HWP(한컴)·MS Print-To-PDF 산출물 보정 (docs/TDD.md §7.7 step 2).

실제 한글 공공 가이드라인 PDF(docs/pdf/*) 분석으로 확인한 결함만 보정한다 (가이드 §5.1.2):

1. 심볼 폰트 글머리표: Wingdings 글리프가 Latin 문자로 추출된다
   (`l`=●, `Ÿ`=•, `è`=➔, `§`=▪ …) — **폰트명이 Wingdings/Webdings 인 span 에서만** 치환한다.
2. PUA(U+F020–U+F0FF): Symbol/Wingdings 글머리표가 사설 영역 코드로 추출된다 → 기호로 치환.
3. 깨진 ToUnicode 매핑: 특정 한글 폰트(KoPubWorldDotum 계열)가 가운뎃점을 `䞻`(U+47BB)로 낸다.
4. 호환 문자 통일: `ㆍ`(아래아, HWP 가운뎃점) `･` `∙` `‧` → `·`, 반각 `｢｣` → `「」`, NBSP/zero-width 제거.

NFKC 는 쓰지 않는다 — 법령 문서의 `①②③`(항 번호)·`㈜` 가 평문 숫자로 뭉개진다. NFC + 명시 치환표만.
순수 함수만 둔다 (PyMuPDF/pdfplumber 비의존) → 단위 테스트 용이.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# Wingdings 코드(바이트) → 의미가 같은 Unicode 기호. 미등록 코드는 "•" 로 대체한다.
_WINGDINGS: dict[int, str] = {
    0x6C: "●",
    0x6D: "○",
    0x6E: "■",
    0x6F: "□",
    0x71: "❑",
    0x75: "◆",
    0x76: "❖",
    0x77: "◆",
    0x9E: "·",
    0x9F: "•",
    0xA1: "○",
    0xA7: "▪",
    0xA8: "◻",
    0xD8: "➢",
    0xE0: "→",
    0xE8: "➔",
    0xF0: "⇨",
    0xFB: "✗",
    0xFC: "✓",
    0xFE: "☑",
}
_DEFAULT_SYMBOL = "•"
_SYMBOL_FONT_RE = re.compile(r"wingdings|webdings", re.IGNORECASE)

# 폰트와 무관하게 치환하는 문자표 (깨진 매핑 + 호환 문자).
_CHAR_MAP: dict[str, str] = {
    "䞻": "·",  # 䞻 — KoPubWorldDotum 계열 ToUnicode 결함 (가운뎃점)
    "ㆍ": "·",  # ㆍ HANGUL LETTER ARAEA — HWP 가 가운뎃점으로 사용
    "･": "·",  # ･ HALFWIDTH KATAKANA MIDDLE DOT
    "∙": "·",  # ∙ BULLET OPERATOR
    "‧": "·",  # ‧ HYPHENATION POINT
    "｢": "「",  # ｢
    "｣": "」",  # ｣
    " ": " ",  # NBSP
    "　": " ",  # IDEOGRAPHIC SPACE
    "​": "",  # ZERO WIDTH SPACE
    "‌": "",
    "‍": "",
    "﻿": "",  # BOM
}
_TRANSLATE = str.maketrans(_CHAR_MAP)

_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
# 머리말/꼬리말 비교 키: 숫자를 # 로 뭉개 "- 4 -" / "- 5 -" 를 같은 줄로 본다.
_DIGITS_RE = re.compile(r"\d+")
# 쪽 번호만 있는 줄: "4", "- 4 -", "| 18", "18 |", "4 / 39" (4자리는 연도 "2026" 과 겹쳐 제외)
_PAGE_NUMBER_RE = re.compile(r"^[\s\-–—|·]*\d{1,3}(\s*/\s*\d{1,3})?[\s\-–—|·]*$")
# 스크램블 판정용: 구두점만 있는 줄
_PUNCT_ONLY_RE = re.compile(r"^[\s.,·:;!?()\[\]{}「」『』“”‘’'\"\-–—/]+$")


def _is_pua_symbol(ch: str) -> bool:
    return 0xF020 <= ord(ch) <= 0xF0FF


def _symbol_for_code(code: int) -> str:
    return _WINGDINGS.get(code, _DEFAULT_SYMBOL)


def _wingdings_char(ch: str) -> str:
    """Wingdings 폰트 span 의 한 글자 → 기호. cp1252 로 원래 바이트를 복원해 조회한다."""
    if ch.isspace():
        return ch
    if _is_pua_symbol(ch):
        return _symbol_for_code(ord(ch) - 0xF000)
    try:
        code = ch.encode("cp1252")[0]
    except (UnicodeEncodeError, IndexError):
        return _DEFAULT_SYMBOL
    return _symbol_for_code(code)


def repair_span(text: str, font: str | None) -> tuple[str, int]:
    """PDF span 한 조각을 보정한다. (보정된 텍스트, 치환 글자 수)를 반환.

    Wingdings 폰트 span 은 글자 단위로 기호 치환, 그 외 폰트는 PUA 글자만 치환한다.
    """
    if font and _SYMBOL_FONT_RE.search(font):
        out = "".join(_wingdings_char(c) for c in text)
        return out, sum(1 for a, b in zip(text, out, strict=True) if a != b)
    if not any(_is_pua_symbol(c) for c in text):
        return text, 0
    out = "".join(_symbol_for_code(ord(c) - 0xF000) if _is_pua_symbol(c) else c for c in text)
    return out, sum(1 for c in text if _is_pua_symbol(c))


def normalize_text(text: str) -> tuple[str, int]:
    """페이지 텍스트 정규화. (정규화 텍스트, 치환 글자 수)를 반환.

    NFC → PUA 기호 치환 → 문자표 치환 → 줄별 공백 정리(연속 공백 축약, 앞뒤 공백 제거).
    """
    text = unicodedata.normalize("NFC", text)
    repaired, n = repair_span(text, None)
    n += sum(repaired.count(src) for src in _CHAR_MAP)
    repaired = repaired.translate(_TRANSLATE)
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in repaired.split("\n")]
    return "\n".join(lines), n


def is_scrambled(text: str, *, min_lines: int = 3, ratio: float = 0.05) -> bool:
    """추출 순서가 깨진 페이지인지 판정한다 (MS Print-To-PDF 류).

    글자 조각이 시각 순서가 아닌 content stream 순서로 나오면 쉼표·마침표가 독립된 줄로 떨어진다.
    구두점-only 줄이 `min_lines` 이상이고 비율이 `ratio` 이상이면 스크램블로 본다.
    (실측: 정상 HWP PDF 최대 2줄/3%, Print-To-PDF 최대 77줄/52%)
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    punct = sum(1 for ln in lines if _PUNCT_ONLY_RE.match(ln))
    return punct >= min_lines and punct / len(lines) >= ratio


def strip_headers_footers(
    pages: list[str],
    *,
    zone: int = 3,
    min_pages: int = 3,
    min_ratio: float = 0.3,
    max_len: int = 40,
) -> tuple[list[str], int]:
    """반복 머리말/꼬리말과 쪽 번호 줄을 제거한다. (정리된 페이지 목록, 제거 줄 수)를 반환.

    - 각 페이지 위/아래 `zone` 줄 중 `max_len` 자 이하인 짧은 줄만 후보로 본다
      (본문 중간 줄·긴 문장은 반복되어도 건드리지 않는다 — 서식이 반복되는 점검표 등 보호).
    - 숫자를 뭉갠 키가 `min_pages` 이상 **그리고** 텍스트 페이지의 `min_ratio` 이상에서 반복되면 제거.
    - 쪽 번호만 있는 줄(`- 4 -`, `| 18`)은 반복 여부와 무관하게 zone 안에서 제거.
    """
    split = [[ln for ln in p.split("\n") if ln.strip()] for p in pages]
    text_pages = sum(1 for lines in split if lines)
    counts: Counter[str] = Counter()
    for lines in split:
        keys = {_key(ln) for ln in _zone_lines(lines, zone) if len(ln.strip()) <= max_len}
        counts.update(keys)
    threshold = max(min_pages, int(text_pages * min_ratio + 0.999))
    repeated = {k for k, c in counts.items() if c >= threshold}

    out: list[str] = []
    removed = 0
    for lines in split:
        n = len(lines)
        kept: list[str] = []
        for i, ln in enumerate(lines):
            in_zone = i < zone or i >= n - zone
            if in_zone and (_PAGE_NUMBER_RE.match(ln) or _key(ln) in repeated):
                removed += 1
                continue
            kept.append(ln)
        out.append("\n".join(kept))
    return out, removed


def _zone_lines(lines: list[str], zone: int) -> list[str]:
    if len(lines) <= zone * 2:
        return lines
    return lines[:zone] + lines[-zone:]


def _key(line: str) -> str:
    return _DIGITS_RE.sub("#", line.strip())

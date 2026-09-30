"""한글 PDF 텍스트 정규화 단위 테스트 (FR-PARSER-002/003, 가이드 §5.1.2).

입력 예시는 docs/pdf/* 실문서(HWP·Print-To-PDF 산출물)에서 관찰한 추출 결과 그대로다.
"""

from __future__ import annotations

from ingestion.parser.korean_text import (
    is_scrambled,
    normalize_text,
    repair_span,
    strip_headers_footers,
)


def test_fr_parser_003_wingdings_span_bullets_restored() -> None:
    # Wingdings 'l'(●) · 'Ÿ'(•, cp1252 0x9F) · 'è'(➔) · '§'(▪)
    assert repair_span("l", "Wingdings-Regular") == ("●", 1)
    assert repair_span("Ÿ", "Wingdings-Regular") == ("•", 1)
    assert repair_span("è", "ABCDEF+Wingdings") == ("➔", 1)
    assert repair_span("§ ", "Wingdings-Regular") == ("▪ ", 1)


def test_fr_parser_003_non_symbol_font_latin_untouched() -> None:
    # 일반 폰트의 'l' 은 영문자 그대로 (폰트명으로만 판단)
    assert repair_span("level", "KoPubDotumLight") == ("level", 0)


def test_fr_parser_003_pua_bullets_replaced_any_font() -> None:
    text, n = repair_span("본 가이드라인은", "Haansoft-Batang")
    assert text == "●본 가이드라인은"
    assert n == 1
    assert repair_span(" 완료", "CIDFont+F7")[0] == "✓ 완료"
    # 미등록 코드는 기본 글머리표
    assert repair_span("", None)[0] == "•"


def test_fr_parser_003_normalize_middle_dots_and_brackets() -> None:
    raw = "개발䞻운영 · 제품･서비스 · 개발ㆍ제조 ｢기본법｣ 제31조  (제1항)"
    text, n = normalize_text(raw)
    assert text == "개발·운영 · 제품·서비스 · 개발·제조 「기본법」 제31조 (제1항)"
    assert n >= 6


def test_fr_parser_003_normalize_keeps_circled_numbers() -> None:
    # NFKC 를 쓰지 않으므로 법령 항 번호(①)가 보존된다
    text, _ = normalize_text("① 인공지능사업자는  \n② 제1항에 따라 ")
    assert text == "① 인공지능사업자는\n② 제1항에 따라"


def test_fr_parser_003_is_scrambled_detects_print_to_pdf_order() -> None:
    scrambled = "\n".join(
        [
            "본 절에서는 국내외 주요 기준과의 연계성을 토대로",
            "고영향 인공",
            ". ",
            "지능의 사회적 파급력을 고려하여",
            ", ",
            "기술적정책적 지원 체계를 포함하여",
            ", ",
            "·",
        ]
    )
    assert is_scrambled(scrambled)
    normal = (
        "제6조(위험의 완화 조치)\n① 인공지능사업자는 위험평가 결과를 바탕으로\n-\n조치를 수립한다."
    )
    assert not is_scrambled(normal)
    assert not is_scrambled("")


def test_fr_parser_002_strip_headers_footers_removes_running_lines() -> None:
    body = "인공지능사업자는 위험평가 결과를 바탕으로 위험을 완화하기 위한 조치를 수립 및 시행하여야 한다."
    titles = ["목적", "정의", "적용 범위", "위험평가", "위험완화", "보고"]
    pages = [
        f"인공지능 안정성 확보 가이드라인\n{body}\n제{i}조({t})\n{body}\n- {i} -"
        for i, t in enumerate(titles, start=1)
    ]
    cleaned, removed = strip_headers_footers(pages)
    assert removed == 12  # 머리말 6 + 쪽 번호 6
    # 모든 쪽에 반복되는 긴 본문 문장(> max_len)은 zone 안이어도 보존
    assert cleaned[0] == f"{body}\n제1조(목적)\n{body}"


def test_fr_parser_002_strip_headers_footers_keeps_rare_and_year_lines() -> None:
    pages = [
        "2026\n고영향 인공지능 판단 가이드라인",
        "개요\n본문 A",
        "개요\n본문 B",
        "용어\n본문 C",
        "절차\n본문 D",
        "부록\n본문 E",
        "부록\n본문 F",
        "참고\n본문 G",
        "참고\n본문 H",
        "끝\n본문 I",
    ]
    cleaned, removed = strip_headers_footers(pages)
    # "개요"/"부록"/"참고" 는 2쪽씩만 반복(min_pages=3 미만), "2026" 은 4자리 → 쪽 번호 아님
    assert removed == 0
    assert cleaned == pages

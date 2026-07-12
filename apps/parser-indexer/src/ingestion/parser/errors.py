"""파서/색인 예외 — 명확한 error code 부여 (FR-PARSER-006, FR-IDX-007)."""

from __future__ import annotations


class ParseFailed(Exception):
    """파싱 실패. `.code`로 실패 사유를 구분한다 (§7.7 step 2).

    코드 예시:
    - SCANNED_NO_OCR   : 스캔 문서(텍스트 비율 < 5%)이나 OCR 비활성
    - ENCRYPTED        : 암호화되어 열 수 없음
    - CORRUPT          : 파일 손상/파싱 불가
    - UNSUPPORTED_TYPE : 지원하지 않는 확장자
    - EMPTY            : 추출된 텍스트가 없음
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"


class IndexFailed(Exception):
    """색인 검증 실패 (§7.7 step 8, FR-IDX-007)."""

    def __init__(self, message: str, *, code: str = "INDEX_VALIDATION_FAILED") -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"

"""Secret 마스킹 (§11 #3, §23.4).

두 층으로 마스킹한다.
1. 키 이름: token/webhook/secret/password/signing_key/authorization 가 포함된 키의 값을 `***` 로 치환.
2. 값 패턴: 키 이름과 무관하게 문자열 값 안의 DSN 비밀번호(`scheme://user:pw@host`),
   Mattermost Incoming Webhook 경로(`/hooks/<id>`), `Bearer <token>` 을 치환한다.
   — 예외 메시지(psycopg/httpx 오류에 URL 이 포함됨)나 f-string 으로 끼어든 secret 을 위한 방어선.
Secret 값(Outgoing Token, Incoming Webhook URL)은 로그에 절대 노출 금지 (§3.2).
"""

from __future__ import annotations

import re
from typing import Any

# 키 이름에 아래 부분 문자열이 포함되면 마스킹한다.
_SENSITIVE_HINTS = ("token", "secret", "webhook", "password", "signing_key", "authorization")
_MASK = "***"

# 값 패턴 — 순서대로 적용.
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:password@host → scheme://user:***@host  (DSN, Redis URL 등)
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]*:)[^@\s/]+(@)"), r"\1***\2"),
    # Mattermost Incoming Webhook: .../hooks/<key>  → .../hooks/***
    (re.compile(r"(/hooks/)[A-Za-z0-9_-]+"), r"\1***"),
    # Authorization: Bearer <token>
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1***"),
)


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(hint in k for hint in _SENSITIVE_HINTS)


def mask_text(value: str) -> str:
    """문자열 값 안의 secret 패턴을 치환한다."""
    for pattern, repl in _VALUE_PATTERNS:
        value = pattern.sub(repl, value)
    return value


def mask_secrets(value: Any) -> Any:
    """dict/list/str 을 재귀적으로 순회하며 민감 키의 값과 문자열 내 secret 패턴을 마스킹한다."""
    if isinstance(value, dict):
        return {k: (_MASK if _is_sensitive(str(k)) else mask_secrets(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(mask_secrets(v) for v in value)
    if isinstance(value, str):
        return mask_text(value)
    return value


def _structlog_processor(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor로 사용 — 모든 로그 이벤트에 마스킹 적용 (dict_tracebacks 이후에 위치)."""
    return mask_secrets(event_dict)

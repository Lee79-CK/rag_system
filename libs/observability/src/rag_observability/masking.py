"""Secret 마스킹 (§11 #3, §23.4).

로그 이벤트 dict에서 token/webhook/secret/url 등 민감 키를 `***`로 치환한다.
Secret 값(Outgoing Token, Incoming Webhook URL)은 로그에 절대 노출 금지 (§3.2).
"""

from __future__ import annotations

from typing import Any

# 키 이름에 아래 부분 문자열이 포함되면 마스킹한다.
_SENSITIVE_HINTS = ("token", "secret", "webhook", "password", "signing_key", "authorization")
_MASK = "***"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(hint in k for hint in _SENSITIVE_HINTS)


def mask_secrets(value: Any) -> Any:
    """dict/list를 재귀적으로 순회하며 민감 키의 값을 마스킹한다."""
    if isinstance(value, dict):
        return {k: (_MASK if _is_sensitive(str(k)) else mask_secrets(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(mask_secrets(v) for v in value)
    return value


def _structlog_processor(_logger: Any, _method: str, event_dict: dict) -> dict:
    """structlog processor로 사용 — 모든 로그 이벤트에 마스킹 적용."""
    return mask_secrets(event_dict)

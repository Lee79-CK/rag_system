"""structlog JSON 로깅 설정 (§12.2).

`channel_id/post_id/job_id/user_id/operation/duration_ms/status`는
contextvars로 자동 포함된다. Secret은 masking processor로 제거된다.
"""

from __future__ import annotations

from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
)

from rag_observability.masking import _structlog_processor

_configured = False


def configure_logging(service_name: str, *, level: str = "INFO") -> None:
    """전 서비스 공통 로깅 설정. lifespan/부팅 시 1회 호출한다."""
    global _configured
    structlog.configure(
        processors=[
            merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,  # 예외를 dict 로 펼친 뒤에 마스킹해야 traceback 도 걸러진다
            _structlog_processor,  # secret 마스킹 (§11 #3) — 키 이름 + 값 패턴(DSN 비밀번호, /hooks/ URL)
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_int(level)),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)
    _configured = True


def _level_to_int(level: str) -> int:
    import logging

    return getattr(logging, level.upper(), logging.INFO)


def get_logger(name: str | None = None) -> Any:
    if not _configured:
        configure_logging("unknown")
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """요청 스코프 contextvars 바인딩 (request_id/trace_id/channel_id 등)."""
    bind_contextvars(**kwargs)


def clear_context() -> None:
    clear_contextvars()

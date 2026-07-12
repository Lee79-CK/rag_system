"""tenacity 기반 재시도 설정 (§3.1). Incoming Webhook/Upstream 호출용 지수 Backoff."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def http_retry(
    attempts: int = 3,
    *,
    multiplier: float = 2.0,
    max_wait: float = 8.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """지수 Backoff 재시도 데코레이터 (예: 2s, 4s, 8s — §7.1.2).

    reraise=True로 최종 실패 시 원 예외를 그대로 올린다.
    """
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=multiplier, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        reraise=True,
    )

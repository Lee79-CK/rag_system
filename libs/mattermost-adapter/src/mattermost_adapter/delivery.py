"""Incoming Webhook 게시 (§7.1.2).

RAG Worker가 이 `deliver()`를 직접 호출한다 (서비스 홉 감소, DEC 확정 §7.1.2).
Secret(Incoming Webhook URL)은 로그에 남기지 않는다 — secret_ref 이름만 기록 (§7.1.2 MUST).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from rag_common.retry import http_retry
from rag_schemas import IncomingWebhookMessage

from mattermost_adapter.render import DEFAULT_MAX_POST_CHARS, split_post


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    attempts: int
    http_status: int | None = None
    error: str | None = None
    posted_parts: int = 0


@dataclass(slots=True)
class DeliveryConfig:
    connect_timeout: float = 3.0
    read_timeout: float = 10.0
    max_attempts: int = 3
    max_post_chars: int = DEFAULT_MAX_POST_CHARS


async def deliver(
    webhook_url: str,
    message: IncomingWebhookMessage,
    *,
    secret_ref: str,
    config: DeliveryConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> DeliveryResult:
    """답변을 Incoming Webhook으로 게시한다. 실패 시 지수 backoff 재시도 (2s/4s/8s).

    `secret_ref`는 로깅/추적용 이름일 뿐 URL이 아니다. URL은 절대 반환/기록하지 않는다.
    """
    cfg = config or DeliveryConfig()
    parts = split_post(message.text, cfg.max_post_chars)

    timeout = httpx.Timeout(
        connect=cfg.connect_timeout,
        read=cfg.read_timeout,
        write=cfg.read_timeout,
        pool=cfg.read_timeout,
    )
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)

    attempts = 0
    last_status: int | None = None

    @http_retry(attempts=cfg.max_attempts, exceptions=(httpx.HTTPError,))
    async def _post(body: dict) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        resp = await http.post(webhook_url, json=body)
        resp.raise_for_status()
        return resp

    try:
        for idx, part in enumerate(parts):
            # 분할 게시: 첫 파트에만 attachments(피드백 버튼)를 포함한다.
            body = message.model_copy(
                update={"text": part, "attachments": message.attachments if idx == 0 else []}
            ).model_dump()
            resp = await _post(body)
            last_status = resp.status_code
        return DeliveryResult(
            ok=True, attempts=attempts, http_status=last_status, posted_parts=len(parts)
        )
    except httpx.HTTPStatusError as e:
        return DeliveryResult(
            ok=False,
            attempts=attempts,
            http_status=e.response.status_code,
            error="http_status_error",
        )
    except httpx.HTTPError as e:
        return DeliveryResult(
            ok=False, attempts=attempts, http_status=last_status, error=type(e).__name__
        )
    finally:
        if owns_client:
            await http.aclose()

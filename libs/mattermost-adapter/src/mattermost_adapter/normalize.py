"""Mattermost Outgoing payload 정규화 — JSON과 form-urlencoded 모두 수용 (§4.1, §7.1.1 step1)."""

from __future__ import annotations

from typing import Any

from rag_schemas import OutgoingWebhookPayload


def normalize_outgoing_payload(data: dict[str, Any]) -> OutgoingWebhookPayload:
    """dict(JSON 파싱 결과 또는 form dict)를 표준 OutgoingWebhookPayload로 변환.

    form-urlencoded는 모든 값이 문자열이므로 timestamp 등 숫자 필드를 보정한다.
    """
    payload = dict(data)

    ts = payload.get("timestamp")
    if isinstance(ts, str) and ts.strip():
        try:
            payload["timestamp"] = int(ts)
        except ValueError:
            payload["timestamp"] = None

    # Mattermost form payload는 root_id가 없을 수 있다 → 기본 빈 문자열.
    if payload.get("root_id") is None:
        payload.pop("root_id", None)

    return OutgoingWebhookPayload.model_validate(payload)

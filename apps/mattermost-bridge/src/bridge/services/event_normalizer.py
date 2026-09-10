"""OutgoingWebhookPayload → 내부 표준 ChatRequest 변환 (docs/TDD.md §4.2, §7.1.1 step6).

Mattermost 종속성을 제거한 순수 질문(message)을 만든다 (NFR-MAINT-006).
"""

from __future__ import annotations

from rag_schemas import ChannelBinding, ChannelMode, ChatRequest, OutgoingWebhookPayload


def _strip_trigger(text: str, trigger: str | None) -> str:
    """TRIGGER_WORD 모드에서 선행 trigger prefix를 제거한다 (`!rag 질문` → `질문`)."""
    stripped = text.lstrip()
    if trigger and stripped.startswith(trigger):
        return stripped[len(trigger) :].strip()
    return text.strip()


def to_chat_request(
    payload: OutgoingWebhookPayload,
    binding: ChannelBinding,
    trace_id: str,
    *,
    default_trigger: str | None = None,
) -> ChatRequest:
    """정규화된 payload와 binding으로 내부 ChatRequest를 만든다.

    TRIGGER_WORD 모드면 trigger prefix를 제거한 순수 질문을 `message`로 담는다.
    binding.trigger_word 가 비어 있으면 전역 기본값(`MATTERMOST_DEFAULT_TRIGGER_WORD`)을 쓴다 —
    outgoing.py step6 의 게이트 판정과 동일한 trigger 를 써야 prefix 가 LLM 에 새지 않는다 (FR-MM-010).
    """
    message = payload.text.strip()
    if binding.mode == ChannelMode.TRIGGER_WORD:
        message = _strip_trigger(payload.text, binding.trigger_word or default_trigger)

    return ChatRequest(
        source="mattermost",
        team_id=payload.team_id,
        channel_id=payload.channel_id,
        channel_name=payload.channel_name,
        user_id=payload.user_id,
        user_name=payload.user_name,
        post_id=payload.post_id,
        root_id=payload.root_id or None,
        message=message,
        trace_id=trace_id,
    )

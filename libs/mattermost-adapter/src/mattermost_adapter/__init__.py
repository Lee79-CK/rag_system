"""mattermost_adapter — Mattermost 종속 payload를 내부 표준으로 변환하는 Adapter (§13.2).

RAG Domain Logic은 포함하지 않는다.
"""

from mattermost_adapter.delivery import DeliveryResult, deliver
from mattermost_adapter.normalize import normalize_outgoing_payload
from mattermost_adapter.render import (
    build_feedback_attachment,
    feedback_signature,
    render_answer,
    split_post,
)

__all__ = [
    "DeliveryResult",
    "deliver",
    "normalize_outgoing_payload",
    "build_feedback_attachment",
    "feedback_signature",
    "render_answer",
    "split_post",
]

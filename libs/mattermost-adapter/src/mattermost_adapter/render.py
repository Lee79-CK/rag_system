"""답변 Markdown 렌더링 + 피드백 버튼 attachment (§7.2.5, v1.1)."""

from __future__ import annotations

import hmac
from hashlib import sha256

from rag_schemas import RagCompletion

DEFAULT_MAX_POST_CHARS = 12000  # MATTERMOST_MAX_POST_CHARS (§7.1.2 step3, FR-MM-016)


def render_answer(user_name: str, completion: RagCompletion, *, mention: bool) -> str:
    """RagCompletion → Mattermost Markdown 본문 (§7.2.5)."""
    lines: list[str] = []
    if mention:
        lines.append(f"@{user_name} **답변**\n")
    lines.append(completion.answer)
    if completion.citations:
        lines.append("\n**근거 문서**")
        for i, c in enumerate(completion.citations, 1):
            loc = f"p.{c.page}" if c.page else ""
            lines.append(f"{i}. `{c.document_name}` {loc} — {c.section or ''}\n   - {c.excerpt}")
    if completion.insufficient_evidence:
        lines.append(
            "\n> 문서 근거가 충분하지 않습니다. 질문을 구체화하거나 관련 문서 등록을 요청해 주세요."
        )
    return "\n".join(lines)


def feedback_signature(signing_key: bytes, message_id: str, value: str) -> str:
    """HMAC-SHA256(FEEDBACK_SIGNING_KEY, f"{message_id}:{value}") — §4.5, §7.1.4."""
    return hmac.new(signing_key, f"{message_id}:{value}".encode(), sha256).hexdigest()


def build_feedback_attachment(
    message_id: str,
    chat_job_id: str,
    signing_key: bytes,
    action_url: str,
) -> dict:
    """답변 Post에 붙이는 👍/👎 Interactive Buttons (§7.2.5).

    Incoming Webhook payload의 "attachments" 필드에 포함한다.
    """

    def ctx(value: str) -> dict:
        return {
            "action": "feedback",
            "message_id": message_id,
            "chat_job_id": chat_job_id,
            "value": value,
            "sig": feedback_signature(signing_key, message_id, value),
        }

    return {
        "text": "이 답변이 도움이 되었나요?",
        "actions": [
            {
                "id": "fb_up",
                "name": "👍 도움됨",
                "integration": {"url": action_url, "context": ctx("UP")},
            },
            {
                "id": "fb_down",
                "name": "👎 아쉬움",
                "integration": {"url": action_url, "context": ctx("DOWN")},
            },
        ],
    }


def split_post(text: str, max_chars: int = DEFAULT_MAX_POST_CHARS) -> list[str]:
    """MATTERMOST_MAX_POST_CHARS 초과 시 줄 경계 기준 분할 게시 (FR-MM-016)."""
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.split("\n"):
        # 한 줄 자체가 상한을 넘으면 강제로 잘라 넣는다.
        while len(line) > max_chars:
            if current:
                parts.append("\n".join(current))
                current, length = [], 0
            parts.append(line[:max_chars])
            line = line[max_chars:]
        add_len = len(line) + (1 if current else 0)
        if length + add_len > max_chars:
            parts.append("\n".join(current))
            current, length = [line], len(line)
        else:
            current.append(line)
            length += add_len
    if current:
        parts.append("\n".join(current))
    return parts

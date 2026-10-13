"""답변 렌더링: RagCompletion → (Markdown 본문, blocks) + 피드백 토큰 (§7.2.5, v1.1)."""

from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Any

from rag_schemas import RagCompletion

ERROR_TEXT = "⚠️ 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
INSUFFICIENT_NOTE = (
    "문서 근거가 충분하지 않습니다. 질문을 구체화하거나 관련 문서 등록을 요청해 주세요."
)
DIRECT_NOTE = (
    "📎 사내 문서를 검색하지 않고 LLM 이 직접 답변했습니다. 사내 정보는 정확하지 않을 수 있습니다."
)
_EXCERPT_MAX = 200


def render_answer(
    completion: RagCompletion, *, user_name: str, mention: bool
) -> tuple[str, list[dict[str, Any]]]:
    """본문(markdown)과 chat-web BlockRenderer 용 blocks 를 만든다.

    - 본문: (mention 시 `@user `) + LLM 답변. 스트리밍 누적 결과와 동일한 텍스트.
    - 근거 문서: `table` block (#, 문서, 위치, 발췌) — Mattermost 시절 "근거 문서" 목록 대체.
    - 근거 부족: `context` block 안내.
    - LLM 직접 대화(`/`, FR-CHAT-014): 근거 표 없이 `context` block 안내.
    """
    message = f"@{user_name} {completion.answer}" if mention else completion.answer
    blocks: list[dict[str, Any]] = []
    if completion.citations:
        rows = []
        for i, c in enumerate(completion.citations, 1):
            loc = " · ".join(x for x in (f"p.{c.page}" if c.page else "", c.section or "") if x)
            rows.append(
                {
                    "n": str(
                        c.ref or i
                    ),  # 본문의 [n] 과 같은 번호 (인용된 문서만이라 비연속일 수 있음)
                    "doc": c.document_name,
                    "loc": loc or "-",
                    "excerpt": c.excerpt[:_EXCERPT_MAX],
                }
            )
        blocks.append(
            {
                "type": "table",
                "block_id": "citations",
                "columns": [
                    {"key": "n", "label": "#", "align": "right"},
                    {"key": "doc", "label": "근거 문서", "emphasis": True},
                    {"key": "loc", "label": "위치"},
                    {"key": "excerpt", "label": "발췌"},
                ],
                "rows": rows,
                "source": "사내 문서 RAG 검색",
            }
        )
    if completion.insufficient_evidence:
        blocks.append({"type": "context", "block_id": "insufficient", "text": INSUFFICIENT_NOTE})
    if completion.direct:
        blocks.append({"type": "context", "block_id": "direct", "text": DIRECT_NOTE})
    return message, blocks


def feedback_token(signing_key: bytes, message_id: str, post_id: str) -> str:
    """HMAC-SHA256(FEEDBACK_SIGNING_KEY, f"{message_id}:{post_id}") — §4.5, §7.1.4.

    Bot Post props 에 실어 보내고, /api/v1/actions 가 동일 값을 재계산해 대조한다.
    Post↔답변 message 연결이 위·변조되지 않았음을 보장한다.
    """
    return hmac.new(signing_key, f"{message_id}:{post_id}".encode(), sha256).hexdigest()


def verify_feedback_token(signing_key: bytes, message_id: str, post_id: str, token: str) -> bool:
    if not signing_key or not token:
        return False
    return hmac.compare_digest(feedback_token(signing_key, message_id, post_id), token)

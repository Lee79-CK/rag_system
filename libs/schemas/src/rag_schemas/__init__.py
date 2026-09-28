"""rag_schemas — 전 서비스 공유 Pydantic 스키마 (Single Source of Truth).

docs/TDD.md §4. 서비스별로 스키마를 중복 정의하지 않는다 (§0 규칙 3).
"""

from rag_schemas.binding import (
    ChannelBinding,
    ChannelMode,
    KnowledgeScope,
    scope_key,
)
from rag_schemas.chat import (
    ChatJobStatus,
    ChatRequest,
    Citation,
    ConversationMode,
    RagCompletion,
)
from rag_schemas.document import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    QdrantChunkPayload,
)
from rag_schemas.errors import ErrorDetail, ErrorResponse
from rag_schemas.feedback import (
    FEEDBACK_ACTION_DOWN,
    FEEDBACK_ACTION_UP,
    FeedbackValue,
    MessageFeedback,
    WidgetActionRequest,
)

__all__ = [
    # binding
    "ChannelBinding",
    "ChannelMode",
    "KnowledgeScope",
    "scope_key",
    # chat
    "ChatJobStatus",
    "ChatRequest",
    "Citation",
    "ConversationMode",
    "RagCompletion",
    # document
    "ParsedDocument",
    "ParsedElement",
    "ParsedPage",
    "QdrantChunkPayload",
    # errors
    "ErrorDetail",
    "ErrorResponse",
    # feedback
    "FEEDBACK_ACTION_DOWN",
    "FEEDBACK_ACTION_UP",
    "FeedbackValue",
    "MessageFeedback",
    "WidgetActionRequest",
]
# Web Chat 계약(DTO/WS 이벤트)은 `rag_schemas.webchat` 에서 직접 import 한다.

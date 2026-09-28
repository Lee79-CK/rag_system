"""Web Chat(chat-gateway ↔ chat-web) 계약 스키마 — docs/TDD.md §4.1.

aiops_chatbot Web UI 의 API DTO(`apps/chat-web/src/lib/query/hooks.ts`)와 1:1 대응한다.
필드명을 바꾸면 chat-web 타입도 함께 바꿔야 한다 (camelCase 아님, snake_case 유지).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- WS events
WS_POST_CREATED = "post.created"
WS_POST_UPDATED = "post.updated"
WS_POST_DELETED = "post.deleted"
WS_THREAD_UPDATED = "thread.updated"
WS_LLM_STREAM_DELTA = "llm.stream.delta"
WS_LLM_STREAM_END = "llm.stream.end"
WS_CHANNEL_UPDATED = "channel.updated"
WS_READY = "ready"


def channel_room(channel_id: str) -> str:
    """socket.io room 이름. 채널 멤버만 join 한다 (Channel 격리)."""
    return f"channel:{channel_id}"


def user_room(user_id: str) -> str:
    return f"user:{user_id}"


# ---------------------------------------------------------------- blocks
class HeaderBlock(BaseModel):
    type: Literal["header"] = "header"
    text: str
    block_id: str | None = None


class SectionBlock(BaseModel):
    type: Literal["section"] = "section"
    text: str
    block_id: str | None = None


class MarkdownBlock(BaseModel):
    type: Literal["markdown"] = "markdown"
    text: str = Field(max_length=20000)
    block_id: str | None = None


class ContextBlock(BaseModel):
    type: Literal["context"] = "context"
    text: str
    block_id: str | None = None


class DividerBlock(BaseModel):
    type: Literal["divider"] = "divider"
    block_id: str | None = None


class KvItem(BaseModel):
    k: str
    v: str


class KvListBlock(BaseModel):
    type: Literal["kv_list"] = "kv_list"
    items: list[KvItem]
    block_id: str | None = None


class CodeBlock(BaseModel):
    type: Literal["code"] = "code"
    text: str = Field(max_length=20000)
    lang: str | None = None
    block_id: str | None = None


class TableColumn(BaseModel):
    key: str
    label: str
    align: Literal["left", "right"] | None = None
    emphasis: bool | None = None


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    columns: list[TableColumn]
    rows: list[dict[str, str | int | float | None]]
    footer: list[str] | None = None
    source: str | None = None
    block_id: str | None = None


Block = Annotated[
    HeaderBlock
    | SectionBlock
    | MarkdownBlock
    | ContextBlock
    | DividerBlock
    | KvListBlock
    | CodeBlock
    | TableBlock,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- DTOs
class UserBrief(BaseModel):
    id: str
    display_name: str
    avatar_url: str | None = None
    is_bot: bool = False
    email: str | None = None


PostType = Literal["user", "bot", "system"]


class PostDto(BaseModel):
    id: str
    channel_id: str
    root_id: str | None = None
    type: PostType
    user: UserBrief | None = None
    message: str = ""
    blocks: list[Block] | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    edit_at: str | None = None
    delete_at: str | None = None
    is_pinned: bool = False
    reply_count: int = 0
    last_reply_at: str | None = None
    participants: list[UserBrief] = Field(default_factory=list)
    reactions: list[dict[str, Any]] = Field(default_factory=list)
    thread: dict[str, Any] | None = None


class SidebarChannel(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    type: Literal["public", "private"] = "public"
    customer_tag: str | None = None
    env_tag: str | None = None
    unread: int = 0
    mention_count: int = 0
    is_muted: bool = False
    is_favorite: bool = False
    role: str = "member"
    dm_peer: UserBrief | None = None


class WorkspaceBrief(BaseModel):
    id: str
    name: str
    slug: str


class Sidebar(BaseModel):
    workspace: WorkspaceBrief
    favorites: list[SidebarChannel] = Field(default_factory=list)
    customers: list[dict[str, Any]] = Field(default_factory=list)
    other: list[SidebarChannel] = Field(default_factory=list)
    direct: list[SidebarChannel] = Field(default_factory=list)
    all: list[SidebarChannel] = Field(default_factory=list)


class EffectivePermissions(BaseModel):
    role: str | None = None
    is_member: bool = False
    permissions: dict[str, bool] = Field(default_factory=dict)


class ChannelBindingBrief(BaseModel):
    """Composer 힌트용. knowledge_scope 등 내부 설정은 노출하지 않는다."""

    enabled: bool
    mode: Literal["DEDICATED_CHANNEL", "TRIGGER_WORD"]
    trigger_word: str | None = None
    conversation_mode: Literal["CHANNEL", "THREAD", "STATELESS"]


class ChannelDetail(BaseModel):
    id: str
    name: str
    display_name: str
    type: str
    purpose: str | None = None
    member_count: int = 0
    binding: ChannelBindingBrief | None = None
    me: EffectivePermissions


class ThreadMeta(BaseModel):
    reply_count: int = 0
    participant_count: int = 0


class ThreadDto(BaseModel):
    root: PostDto
    replies: list[PostDto]
    thread: ThreadMeta
    me: EffectivePermissions


class PostListResponse(BaseModel):
    items: list[PostDto]
    has_more: bool


class CreatePostRequest(BaseModel):
    channel_id: str = Field(min_length=1, max_length=64)
    root_id: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=1, max_length=12000)
    client_id: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------- WS payloads
class LlmStreamDelta(BaseModel):
    post_id: str
    channel_id: str
    root_id: str | None = None
    delta: str
    seq: int


class LlmStreamEnd(BaseModel):
    post_id: str
    channel_id: str
    root_id: str | None = None
    usage: dict[str, Any] | None = None


class PostDeleted(BaseModel):
    id: str
    channel_id: str
    root_id: str | None = None


# ---------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    """aiops 로그인 계약. 원문 비밀번호는 브라우저를 떠나지 않는다 (prehash 만 전송)."""

    email: str = Field(min_length=3, max_length=254)
    prehash: str = Field(min_length=16, max_length=128)
    client_nonce: str = Field(min_length=8, max_length=64)
    timestamp: int


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str
    role: Literal["user", "admin"]
    avatar_url: str | None = None
    must_change_password: bool = False


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int
    user: AuthUser


class PasswordChangeRequest(BaseModel):
    current_prehash: str = Field(min_length=16, max_length=128)
    new_prehash: str = Field(min_length=16, max_length=128)
    policy: dict[str, int] | None = None  # {length, kinds} — 클라이언트 정책 메타

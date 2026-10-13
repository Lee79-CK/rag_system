"""채널 API (docs/TDD.md §7.1.6) — 멤버십 기반. 비멤버 채널은 존재 여부도 노출하지 않는다."""

from __future__ import annotations

from typing import Annotated

from chat_adapter import to_post_dto
from fastapi import APIRouter, Query, Response
from rag_schemas.webchat import (
    ChannelBindingBrief,
    ChannelDetail,
    EffectivePermissions,
    PostListResponse,
    Sidebar,
    SidebarChannel,
    WorkspaceBrief,
)

from gateway.api.responses import ApiError
from gateway.deps import AppSettings, CurrentUser, Store
from gateway.repos import ChannelRecord, ChatStore, UserRecord

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def permissions_for(
    role: str | None, user: UserRecord, *, bot_enabled: bool
) -> EffectivePermissions:
    """chat-web 이 참조하는 키: post / reply / use_bot / moderate."""
    is_member = role is not None
    moderate = is_member and (role == "channel_admin" or user.role == "admin")
    return EffectivePermissions(
        role=role,
        is_member=is_member,
        permissions={
            "post": is_member,
            "reply": is_member,
            "use_bot": is_member and bot_enabled,
            "moderate": moderate,
        },
    )


def require_member(
    store: ChatStore, id_or_name: str, user: UserRecord
) -> tuple[ChannelRecord, str]:
    ch = store.get_channel(id_or_name)
    role = store.get_member_role(ch.id, user.id) if ch else None
    if ch is None or role is None:
        # 비멤버/미존재 동일 응답 (Channel 격리 — 존재 여부 비노출)
        raise ApiError(404, "CHANNEL_NOT_FOUND", "채널을 찾을 수 없거나 접근 권한이 없습니다.")
    return ch, role


@router.get("/sidebar", response_model=Sidebar)
async def sidebar(user: CurrentUser, store: Store, settings: AppSettings) -> Sidebar:
    items = [
        SidebarChannel(
            id=m.channel.id,
            name=m.channel.name,
            display_name=m.channel.display_name,
            type="private" if m.channel.type == "private" else "public",
            unread=m.unread,
            role=m.role,
        )
        for m in store.list_member_channels(user.id)
    ]
    return Sidebar(
        workspace=WorkspaceBrief(
            id=settings.chat_workspace_slug,
            name=settings.chat_workspace_name,
            slug=settings.chat_workspace_slug,
        ),
        other=items,
        all=items,
    )


@router.get("/{id_or_name}", response_model=ChannelDetail)
async def channel_detail(id_or_name: str, user: CurrentUser, store: Store) -> ChannelDetail:
    ch, role = require_member(store, id_or_name, user)
    binding = store.get_binding(ch.id)
    return ChannelDetail(
        id=ch.id,
        name=ch.name,
        display_name=ch.display_name,
        type=ch.type,
        purpose=ch.purpose,
        member_count=len(store.list_members(ch.id)),
        binding=ChannelBindingBrief(
            enabled=binding.enabled,
            mode=binding.mode.value,
            trigger_word=binding.trigger_word,
            conversation_mode=binding.conversation_mode.value,
            direct_llm_enabled=binding.direct_llm_enabled,
        )
        if binding
        else None,
        me=permissions_for(role, user, bot_enabled=bool(binding and binding.enabled)),
    )


@router.get("/{channel_id}/posts", response_model=PostListResponse)
async def channel_posts(
    channel_id: str,
    user: CurrentUser,
    store: Store,
    limit: Annotated[int, Query(ge=1, le=200)] = 80,
    before: Annotated[str | None, Query(max_length=64)] = None,
) -> PostListResponse:
    ch, _ = require_member(store, channel_id, user)
    rows, has_more = store.list_root_posts(ch.id, limit=limit, before=before)
    return PostListResponse(items=[to_post_dto(r) for r in rows], has_more=has_more)


@router.get("/{channel_id}/members")
async def channel_members(channel_id: str, user: CurrentUser, store: Store) -> list[dict]:
    ch, _ = require_member(store, channel_id, user)
    return [
        {"user_id": m.id, "display_name": m.display_name, "email": m.email, "is_bot": m.is_bot}
        for m in store.list_members(ch.id)
    ]


@router.post("/{channel_id}/view", status_code=204)
async def mark_viewed(channel_id: str, user: CurrentUser, store: Store) -> Response:
    ch, _ = require_member(store, channel_id, user)
    store.mark_viewed(ch.id, user.id)
    return Response(status_code=204)

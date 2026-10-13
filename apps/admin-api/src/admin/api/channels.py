"""Web Chat 채널 · Binding · 멤버 관리 API — docs/TDD.md §7.5 (§9.6).

채널은 chat-gateway 가 사용자에게 노출하는 대화 공간이며, Binding 은 해당 채널의
RAG 응답 설정(모드/지식 범위/피드백)이다. 멤버십이 곧 Channel 격리 경계다.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import DOC_ADMIN, SYS_ADMIN, Principal, require_roles
from admin.db.models import ChannelBindingRow, ChatChannel, ChatChannelMember, ChatUser
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/chat", tags=["channels"])

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")


# ----- Request models (admin-only local contracts) -----
class ChannelCreate(BaseModel):
    name: str = Field(..., description="URL slug (소문자/숫자/-/_)")
    display_name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="public", pattern="^(public|private)$")
    purpose: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _SLUG.match(v):
            raise ValueError("name must be a lowercase slug")
        return v


class ChannelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, pattern="^(public|private)$")
    purpose: str | None = Field(default=None, max_length=500)


class BindingCreate(BaseModel):
    mode: str = Field(default="DEDICATED_CHANNEL", pattern="^(DEDICATED_CHANNEL|TRIGGER_WORD)$")
    trigger_word: str | None = Field(default=None, max_length=50)
    enabled: bool = False
    knowledge_scope_id: uuid.UUID | None = None
    history_turns: int = Field(default=8, ge=0, le=50)
    mention_user: bool = True
    ack_message_enabled: bool = True
    feedback_enabled: bool = True
    direct_llm_enabled: bool = False


class BindingUpdate(BaseModel):
    mode: str | None = Field(default=None, pattern="^(DEDICATED_CHANNEL|TRIGGER_WORD)$")
    trigger_word: str | None = None
    enabled: bool | None = None
    knowledge_scope_id: uuid.UUID | None = None
    history_turns: int | None = Field(default=None, ge=0, le=50)
    mention_user: bool | None = None
    ack_message_enabled: bool | None = None
    feedback_enabled: bool | None = None
    direct_llm_enabled: bool | None = None


class MemberAdd(BaseModel):
    user_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    role: str = Field(default="member", pattern="^(member|channel_admin)$")


# ----- Views -----
def _channel_view(c: ChatChannel) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "display_name": c.display_name,
        "type": c.type,
        "purpose": c.purpose,
        "archived": c.archived_at is not None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _binding_view(b: ChannelBindingRow) -> dict:
    return {
        "id": str(b.id),
        "channel_ref": str(b.channel_ref),
        "mode": b.mode,
        "trigger_word": b.trigger_word,
        "enabled": b.enabled,
        "knowledge_scope_id": str(b.knowledge_scope_id) if b.knowledge_scope_id else None,
        "history_turns": b.history_turns,
        "mention_user": b.mention_user,
        "ack_message_enabled": b.ack_message_enabled,
        "feedback_enabled": b.feedback_enabled,
        "direct_llm_enabled": b.direct_llm_enabled,
    }


def _member_view(m: ChatChannelMember) -> dict:
    return {
        "user_id": str(m.user_id),
        "email": m.user.email,
        "display_name": m.user.display_name,
        "role": m.role,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    }


def _get_channel(db: Session, channel_id: uuid.UUID) -> ChatChannel:
    channel = db.get(ChatChannel, channel_id)
    if channel is None:
        raise api_error("NOT_FOUND", "Channel을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return channel


def _validate_binding(mode: str | None, trigger_word: str | None) -> None:
    if mode == "TRIGGER_WORD" and not (trigger_word or "").strip():
        raise api_error(
            "TRIGGER_WORD_REQUIRED",
            "TRIGGER_WORD 모드는 trigger_word 가 필요합니다.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


# ----- Channel CRUD -----
@router.post("/channels", status_code=status.HTTP_201_CREATED)
def create_channel(
    body: ChannelCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    dup = db.execute(select(ChatChannel).where(ChatChannel.name == body.name)).scalar_one_or_none()
    if dup is not None:
        raise api_error(
            "DUPLICATE_CHANNEL", "이미 사용 중인 채널 이름입니다.", status.HTTP_409_CONFLICT
        )
    channel = ChatChannel(**body.model_dump())
    db.add(channel)
    db.commit()
    return envelope(_channel_view(channel))


# 조회는 DOC_ADMIN 도 허용 — 문서 허용 채널(ACL) 선택과 채널 관리 읽기 전용 화면에 필요. 쓰기는 SYS_ADMIN.
@router.get("/channels")
def list_channels(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    """목록도 상세와 같은 형태(bindings·member_count) — admin-web 채널 표·RAG 스위치·대시보드가 사용."""
    rows = db.execute(select(ChatChannel).order_by(ChatChannel.name)).scalars().all()
    bindings: dict[uuid.UUID, list[dict]] = {c.id: [] for c in rows}
    for b in db.execute(select(ChannelBindingRow)).scalars():
        if b.channel_ref in bindings:
            bindings[b.channel_ref].append(_binding_view(b))
    counts = dict(
        db.execute(
            select(ChatChannelMember.channel_id, func.count()).group_by(
                ChatChannelMember.channel_id
            )
        ).all()
    )
    return envelope(
        [
            {**_channel_view(c), "bindings": bindings[c.id], "member_count": counts.get(c.id, 0)}
            for c in rows
        ],
        count=len(rows),
    )


@router.get("/channels/{channel_id}")
def get_channel(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    channel = _get_channel(db, channel_id)
    bindings = (
        db.execute(select(ChannelBindingRow).where(ChannelBindingRow.channel_ref == channel_id))
        .scalars()
        .all()
    )
    members = (
        db.execute(select(ChatChannelMember).where(ChatChannelMember.channel_id == channel_id))
        .scalars()
        .all()
    )
    return envelope(
        {
            **_channel_view(channel),
            "bindings": [_binding_view(b) for b in bindings],
            "member_count": len(members),
        }
    )


@router.put("/channels/{channel_id}")
def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    channel = _get_channel(db, channel_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(channel, key, value)
    db.commit()
    return envelope(_channel_view(channel))


# ----- Binding CRUD -----
@router.post("/channels/{channel_id}/bindings", status_code=status.HTTP_201_CREATED)
def create_binding(
    channel_id: uuid.UUID,
    body: BindingCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    _get_channel(db, channel_id)
    _validate_binding(body.mode, body.trigger_word)
    binding = ChannelBindingRow(channel_ref=channel_id, **body.model_dump())
    db.add(binding)
    db.commit()
    return envelope(_binding_view(binding))


@router.put("/bindings/{binding_id}")
def update_binding(
    binding_id: uuid.UUID,
    body: BindingUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    binding = db.get(ChannelBindingRow, binding_id)
    if binding is None:
        raise api_error("NOT_FOUND", "Binding을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    patch = body.model_dump(exclude_unset=True)
    _validate_binding(
        patch.get("mode", binding.mode), patch.get("trigger_word", binding.trigger_word)
    )
    for key, value in patch.items():
        setattr(binding, key, value)
    db.commit()
    return envelope(_binding_view(binding))


@router.post("/bindings/{binding_id}/enable")
def enable_binding(
    binding_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    return _set_enabled(db, binding_id, True)


@router.post("/bindings/{binding_id}/disable")
def disable_binding(
    binding_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    return _set_enabled(db, binding_id, False)


def _set_enabled(db: Session, binding_id: uuid.UUID, enabled: bool) -> dict:
    binding = db.get(ChannelBindingRow, binding_id)
    if binding is None:
        raise api_error("NOT_FOUND", "Binding을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    binding.enabled = enabled
    db.commit()
    return envelope(_binding_view(binding))


# ----- Members (Channel 격리 경계) -----
@router.get("/channels/{channel_id}/members")
def list_members(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    _get_channel(db, channel_id)
    rows = (
        db.execute(select(ChatChannelMember).where(ChatChannelMember.channel_id == channel_id))
        .scalars()
        .all()
    )
    return envelope([_member_view(m) for m in rows], count=len(rows))


@router.post("/channels/{channel_id}/members", status_code=status.HTTP_201_CREATED)
def add_members(
    channel_id: uuid.UUID,
    body: MemberAdd,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    _get_channel(db, channel_id)
    users = db.execute(select(ChatUser).where(ChatUser.id.in_(body.user_ids))).scalars().all()
    found = {u.id for u in users if not u.is_bot}
    missing = [str(u) for u in body.user_ids if u not in found]
    if missing:
        raise api_error(
            "USER_NOT_FOUND",
            "존재하지 않거나 추가할 수 없는 사용자입니다.",
            status.HTTP_404_NOT_FOUND,
            user_ids=missing,
        )
    added = 0
    for uid in found:
        m = db.get(ChatChannelMember, (channel_id, uid))
        if m is None:
            db.add(ChatChannelMember(channel_id=channel_id, user_id=uid, role=body.role))
            added += 1
        else:
            m.role = body.role
    db.commit()
    return envelope({"channel_id": str(channel_id), "added": added})


@router.delete("/channels/{channel_id}/members/{user_id}", status_code=status.HTTP_200_OK)
def remove_member(
    channel_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    m = db.get(ChatChannelMember, (channel_id, user_id))
    if m is None:
        raise api_error("NOT_FOUND", "멤버가 아닙니다.", status.HTTP_404_NOT_FOUND)
    db.delete(m)
    db.commit()
    # 연결 중인 socket 은 다음 ack/subscribe(재연결 포함) 시 room 에서 제거된다 (§7.1.2).
    return envelope({"channel_id": str(channel_id), "user_id": str(user_id), "removed": True})

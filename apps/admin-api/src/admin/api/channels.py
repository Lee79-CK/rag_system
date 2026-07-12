"""Channel + Binding 관리 API — docs/TDD.md §7.5 (§9.6).

HARD RULE (FR-OPS-010, NFR-SEC-006): secret 값(Incoming Webhook URL)은 절대 저장/반환하지 않는다.
DB·응답에는 `secret_ref`(K8s Secret 이름)와 `secret_updated_at`만 존재한다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from rag_schemas import IncomingWebhookMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import MattermostChannel, MattermostChannelBinding
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/mattermost", tags=["channels"])


# ----- Request models (admin-only local contracts) -----
class ChannelCreate(BaseModel):
    team_id: str
    channel_id: str
    channel_name: str
    team_domain: str | None = None
    display_name: str | None = None


class BindingCreate(BaseModel):
    mode: str = "DEDICATED_CHANNEL"
    trigger_word: str | None = None
    enabled: bool = False
    knowledge_scope_id: uuid.UUID | None = None
    history_turns: int = 8
    mention_user: bool = True
    ack_message_enabled: bool = True
    feedback_enabled: bool = True
    secret_ref: str = Field(..., description="K8s Secret 이름만. URL 저장 금지.")


class BindingUpdate(BaseModel):
    mode: str | None = None
    trigger_word: str | None = None
    enabled: bool | None = None
    knowledge_scope_id: uuid.UUID | None = None
    history_turns: int | None = None
    mention_user: bool | None = None
    ack_message_enabled: bool | None = None
    feedback_enabled: bool | None = None


class SecretUpdate(BaseModel):
    secret_ref: str = Field(..., description="K8s Secret 이름. 값(URL)은 K8s Secret으로만 관리.")


# ----- Views (secret 값 노출 금지) -----
def _channel_view(c: MattermostChannel) -> dict:
    return {
        "id": str(c.id),
        "team_id": c.team_id,
        "team_domain": c.team_domain,
        "channel_id": c.channel_id,
        "channel_name": c.channel_name,
        "display_name": c.display_name,
    }


def _binding_view(b: MattermostChannelBinding) -> dict:
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
        # secret_ref는 이름일 뿐 값이 아니다. 값(URL)은 어떤 응답에도 포함하지 않는다.
        "secret_ref": b.secret_ref,
        "secret_updated_at": b.secret_updated_at.isoformat() if b.secret_updated_at else None,
    }


# ----- Channel CRUD -----
@router.post("/channels", status_code=status.HTTP_201_CREATED)
def create_channel(
    body: ChannelCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    dup = db.execute(
        select(MattermostChannel).where(
            MattermostChannel.team_id == body.team_id,
            MattermostChannel.channel_id == body.channel_id,
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise api_error("DUPLICATE_CHANNEL", "이미 등록된 Channel입니다.", status.HTTP_409_CONFLICT)
    channel = MattermostChannel(**body.model_dump())
    db.add(channel)
    db.commit()
    return envelope(_channel_view(channel))


@router.get("/channels")
def list_channels(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    rows = db.execute(select(MattermostChannel)).scalars().all()
    return envelope([_channel_view(c) for c in rows], count=len(rows))


@router.get("/channels/{channel_id}")
def get_channel(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    channel = db.get(MattermostChannel, channel_id)
    if channel is None:
        raise api_error("NOT_FOUND", "Channel을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    bindings = (
        db.execute(
            select(MattermostChannelBinding).where(
                MattermostChannelBinding.channel_ref == channel_id
            )
        )
        .scalars()
        .all()
    )
    return envelope({**_channel_view(channel), "bindings": [_binding_view(b) for b in bindings]})


# ----- Binding CRUD -----
@router.post("/channels/{channel_id}/bindings", status_code=status.HTTP_201_CREATED)
def create_binding(
    channel_id: uuid.UUID,
    body: BindingCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    channel = db.get(MattermostChannel, channel_id)
    if channel is None:
        raise api_error("NOT_FOUND", "Channel을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    binding = MattermostChannelBinding(channel_ref=channel_id, **body.model_dump())
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
    binding = db.get(MattermostChannelBinding, binding_id)
    if binding is None:
        raise api_error("NOT_FOUND", "Binding을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    for key, value in body.model_dump(exclude_unset=True).items():
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
    binding = db.get(MattermostChannelBinding, binding_id)
    if binding is None:
        raise api_error("NOT_FOUND", "Binding을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    binding.enabled = enabled
    db.commit()
    return envelope(_binding_view(binding))


# ----- Secret 등록 (값 반환 절대 금지, FR-OPS-010) -----
@router.post("/channels/{channel_id}/secret")
def update_secret(
    channel_id: uuid.UUID,
    body: SecretUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    """Channel의 binding에 secret_ref를 등록/갱신한다.

    실제 값(Incoming Webhook URL)은 K8s Secret으로만 관리하며 DB에 저장하지 않는다.
    응답에는 secret_ref와 secret_updated_at만 포함한다 (값 반환 금지).
    """
    binding = _binding_for_channel(db, channel_id)
    binding.secret_ref = body.secret_ref
    binding.secret_updated_at = datetime.now(UTC)
    db.commit()
    return envelope(
        {
            "channel_id": str(channel_id),
            "binding_id": str(binding.id),
            "secret_ref": binding.secret_ref,
            "secret_updated_at": binding.secret_updated_at.isoformat(),
        }
    )


# ----- 연결 테스트 (FR-MM-017) -----
@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    """Incoming Webhook으로 테스트 메시지를 게시하고 결과를 반환한다 (§7.5).

    실제 게시는 mattermost_adapter.deliver()로 수행 — 폐쇄망/테스트에서는 mock/stub 가능.
    URL은 secret_ref → K8s Secret에서 로딩하며 로그/응답에 남기지 않는다.
    """
    binding = _binding_for_channel(db, channel_id)
    result = await _run_connection_test(binding)
    return envelope(
        {
            "channel_id": str(channel_id),
            "secret_ref": binding.secret_ref,
            "ok": result["ok"],
            "detail": result.get("detail"),
        }
    )


async def _run_connection_test(binding: MattermostChannelBinding) -> dict:
    """연결 테스트 stub. 폐쇄망 전제상 외부 호출 없이 구성 유효성만 확인한다.

    운영에서는 secret_ref로 URL 로딩 후 mattermost_adapter.deliver(test_message)를 호출한다.
    """
    _ = IncomingWebhookMessage(channel="test", text="RAG 연결 테스트 메시지입니다.")
    if not binding.secret_ref:
        return {"ok": False, "detail": "secret_ref 미등록"}
    return {"ok": True, "detail": "구성 확인 완료 (stub)"}


def _binding_for_channel(db: Session, channel_id: uuid.UUID) -> MattermostChannelBinding:
    channel = db.get(MattermostChannel, channel_id)
    if channel is None:
        raise api_error("NOT_FOUND", "Channel을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    binding = db.execute(
        select(MattermostChannelBinding).where(MattermostChannelBinding.channel_ref == channel_id)
    ).scalar_one_or_none()
    if binding is None:
        raise api_error(
            "BINDING_NOT_FOUND",
            "해당 Channel에 Binding이 없습니다. 먼저 Binding을 생성하세요.",
            status.HTTP_409_CONFLICT,
        )
    return binding

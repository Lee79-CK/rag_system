"""Web Chat 사용자 관리 API — docs/TDD.md §7.5.

- 임시 비밀번호로 생성 → 서버가 prehash(=브라우저와 동일 PBKDF2) → scrypt+pepper 저장.
  `must_change_password=true` 로 첫 로그인 시 변경 유도.
- 임시 비밀번호는 생성/재설정 응답에 **한 번만** 포함되며 DB·로그에 남지 않는다.
"""

from __future__ import annotations

import secrets
import string
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from rag_common.passwords import compute_prehash, hash_prehash, normalize_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.config import get_settings
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import ChatUser
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/chat/users", tags=["chat-users"])


class ChatUserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str = Field(..., min_length=1, max_length=200)
    role: str = Field(default="user", pattern="^(user|admin)$")


class ChatUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None


def _view(u: ChatUser) -> dict:
    # password_hash 는 어떤 응답에도 포함하지 않는다.
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role,
        "is_bot": u.is_bot,
        "is_active": u.is_active,
        "must_change_password": u.must_change_password,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _temp_password() -> str:
    """정책(12자 이상·3종 이상) 충족 임시 비밀번호."""
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{body}!{secrets.choice(string.digits)}A"


def _set_temp_password(user: ChatUser) -> str:
    settings = get_settings()
    pepper = settings.password_pepper()
    if not pepper:
        raise api_error(
            "PEPPER_NOT_CONFIGURED",
            "PASSWORD_PEPPER_FILE 이 설정되지 않았습니다.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    temp = _temp_password()
    prehash = compute_prehash(settings.chat_workspace_slug, user.email, temp)
    user.password_hash = hash_prehash(prehash, pepper)
    user.must_change_password = True
    return temp


def _get(db: Session, user_id: uuid.UUID) -> ChatUser:
    user = db.get(ChatUser, user_id)
    if user is None or user.is_bot:
        raise api_error("NOT_FOUND", "사용자를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return user


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    rows = db.execute(select(ChatUser).order_by(ChatUser.email)).scalars().all()
    return envelope([_view(u) for u in rows], count=len(rows))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: ChatUserCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    email = normalize_email(body.email)
    dup = db.execute(
        select(ChatUser).where(func.lower(ChatUser.email) == email)
    ).scalar_one_or_none()
    if dup is not None:
        raise api_error("DUPLICATE_USER", "이미 등록된 이메일입니다.", status.HTTP_409_CONFLICT)
    user = ChatUser(email=email, display_name=body.display_name, role=body.role)
    temp = _set_temp_password(user)
    db.add(user)
    db.commit()
    return envelope({**_view(user), "temporary_password": temp})


@router.put("/{user_id}")
def update_user(
    user_id: uuid.UUID,
    body: ChatUserUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    user = _get(db, user_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    return envelope(_view(user))


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    user = _get(db, user_id)
    temp = _set_temp_password(user)
    db.commit()
    return envelope({**_view(user), "temporary_password": temp})

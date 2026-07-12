"""운영 설정 API — docs/TDD.md §7.5, §5.1 (FR-OPS-004).

GET 목록 + PUT 갱신(version++). settings 변경은 admin-api만 수행하고 audit_logs에 기록.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import Setting
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    value: Any


def _view(s: Setting) -> dict:
    return {
        "key": s.key,
        "value": s.value,
        "version": s.version,
        "updated_by": str(s.updated_by) if s.updated_by else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
def list_settings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    rows = db.execute(select(Setting).order_by(Setting.key)).scalars().all()
    return envelope([_view(s) for s in rows], count=len(rows))


@router.put("/{key}")
def update_setting(
    key: str,
    body: SettingUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    if body.value is None:
        raise api_error("INVALID_VALUE", "value는 필수입니다.", status.HTTP_400_BAD_REQUEST)
    updated_by = uuid.UUID(principal.id) if principal.id else None
    setting = db.get(Setting, key)
    if setting is None:
        setting = Setting(key=key, value=body.value, version=1, updated_by=updated_by)
        db.add(setting)
    else:
        setting.value = body.value
        setting.version += 1
        setting.updated_by = updated_by
        setting.updated_at = datetime.now(UTC)
    db.commit()
    return envelope(_view(setting))

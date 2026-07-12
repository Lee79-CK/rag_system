"""인증 조회 (whoami) — docs/TDD.md §7.5."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from admin.api.responses import envelope
from admin.core.rbac import Principal, get_current_principal

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/whoami")
def whoami(principal: Principal = Depends(get_current_principal)) -> dict:
    return envelope(
        {
            "id": principal.id,
            "login_id": principal.login_id,
            "display_name": principal.display_name,
            "roles": sorted(principal.roles),
        }
    )

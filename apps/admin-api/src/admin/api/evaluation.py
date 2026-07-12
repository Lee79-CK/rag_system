"""평가(Evaluation) API — docs/TDD.md §7.5 (§13). PoC 최소 stub.

품질 평가 데이터셋/결과 조회. 현재는 빈 데이터셋을 반환한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from admin.api.responses import envelope
from admin.core.rbac import QUALITY_EVALUATOR, SYS_ADMIN, Principal, require_roles

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


@router.get("/datasets")
def list_datasets(
    principal: Principal = Depends(require_roles(SYS_ADMIN, QUALITY_EVALUATOR)),
) -> dict:
    return envelope([], count=0)


@router.get("/runs")
def list_runs(
    principal: Principal = Depends(require_roles(SYS_ADMIN, QUALITY_EVALUATOR)),
) -> dict:
    return envelope([], count=0)

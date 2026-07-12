"""Qdrant 검색 Filter 조립 (§6.3, NFR-SEC-013).

MUST: 모든 검색 요청에 base filter(is_active + allowed_channel_ids)를 무조건 포함한다.
Filter 없는 검색 경로를 만들지 않는다 — Channel 격리 100% (§1.3, §11 #4).
"""

from __future__ import annotations

from qdrant_client import models as qmodels
from rag_schemas import ChannelBinding


def build_filter(binding: ChannelBinding) -> qmodels.Filter:
    """Channel/ACL/활성 문서 Filter를 조립한다. 사후 필터 금지 — 검색 전 강제."""
    must: list[qmodels.FieldCondition] = [
        qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
        qmodels.FieldCondition(
            key="allowed_channel_ids",
            match=qmodels.MatchAny(any=[binding.channel_id]),
        ),
    ]
    ks = binding.knowledge_scope
    if ks.categories:
        must.append(
            qmodels.FieldCondition(key="category", match=qmodels.MatchAny(any=ks.categories))
        )
    if ks.departments:
        must.append(
            qmodels.FieldCondition(key="department", match=qmodels.MatchAny(any=ks.departments))
        )
    if ks.security_levels:
        must.append(
            qmodels.FieldCondition(
                key="security_level", match=qmodels.MatchAny(any=ks.security_levels)
            )
        )
    if ks.document_ids:
        must.append(
            qmodels.FieldCondition(key="document_id", match=qmodels.MatchAny(any=ks.document_ids))
        )
    return qmodels.Filter(must=must)

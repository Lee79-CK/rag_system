"""CH-001~010 Channel 격리 시나리오 (배포 차단 Gate — §13.2, PRD §25.4).

핵심 불변식: 한 Channel의 문서/대화가 다른 Channel의 검색 결과·LLM Context·답변에 절대
포함되지 않는다 (Channel 격리 정확도 100%, PRD §8.1). build_filter 강제 + conversation scope로 보장.
"""

from __future__ import annotations

import pytest
from conftest import (
    CapturingLLM,
    InMemoryQdrant,
    make_binding,
    make_payload,
    make_request,
)
from rag.domain.pipeline import PipelineConfig, RagPipeline
from rag.domain.tokens import HeuristicTokenCounter
from rag.worker.chat_worker import WorkerDeps, process_chat_job
from rag_schemas import RagCompletion, scope_key

CHANNEL_A = "channel-A"
CHANNEL_B = "channel-B"


def _pipeline(qdrant, embedding, reranker, llm, **cfg):
    return RagPipeline(
        embedding=embedding,
        retrieval=qdrant,
        reranker=reranker,
        llm=llm,
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(similarity_threshold=0.0, rerank_score_threshold=0.0, **cfg),
    )


async def _run(binding, message, qdrant, embedding, reranker, llm):
    pipe = _pipeline(qdrant, embedding, reranker, llm)
    return await pipe.run(question=message, binding=binding)


# ---------------------------------------------------------------------------
# CH-001 / CH-010: 문서 ACL — 타 Channel 전용 문서는 검색 0건
# ---------------------------------------------------------------------------
async def test_ch_001_cross_channel_document_not_retrieved(embedding, reranker):
    # 문서 X는 A 전용, 문서 Y는 B 전용
    qdrant = InMemoryQdrant(
        [
            make_payload("x", [CHANNEL_A], "A 전용 문서 내용", title="X"),
            make_payload("y", [CHANNEL_B], "B 전용 문서 내용", title="Y"),
        ]
    )
    llm = CapturingLLM()
    out = await _run(make_binding(CHANNEL_A), "문서 내용 알려줘", qdrant, embedding, reranker, llm)
    titles = {c.document_name for c in out.citations}
    assert "Y" not in titles  # B 전용 문서는 A 답변 근거에 없다
    assert "B 전용 문서 내용" not in "".join(m["content"] for m in llm.messages)


async def test_ch_010_channel_b_gets_zero_when_only_channel_a_doc(embedding, reranker):
    qdrant = InMemoryQdrant([make_payload("x", [CHANNEL_A], "A 전용", title="X")])
    llm = CapturingLLM()
    out = await _run(make_binding(CHANNEL_B), "질문", qdrant, embedding, reranker, llm)
    assert out.insufficient_evidence is True  # 검색 0건 → 근거 부족
    assert out.citations == []
    assert llm.messages == []  # LLM 미호출 (§7.2.3)


# ---------------------------------------------------------------------------
# CH-002 / CH-003: 대화 이력 격리 — 타 Channel 대화가 LLM payload에 없음
# ---------------------------------------------------------------------------
class _FakeStore:
    def __init__(self):
        self.conv: dict[str, list[tuple[str, str]]] = {}

    def seed(self, sk, role, content):
        self.conv.setdefault(sk, []).append((role, content))

    def upsert_conversation(self, *, scope_key, channel_id, root_id, mode):
        self.conv.setdefault(scope_key, [])
        return scope_key

    def load_history(self, conversation_id, limit):
        return list(self.conv.get(conversation_id, []))[-limit:]

    def add_user_message(self, conversation_id, post_id, content):
        self.conv.setdefault(conversation_id, []).append(("user", content))
        return "uid"

    def add_assistant_message(self, conversation_id, content, *, post_id, latency_ms, citations):
        self.conv.setdefault(conversation_id, []).append(("assistant", content))
        return "aid"

    def claim_job(self, job_id):
        return True

    def update_job_status(self, job_id, status, *, error=None, mark_started=False):
        pass


class _NullSink:
    async def push(self, delta):
        pass

    async def flush(self):
        pass


class _FakeDelivery:
    """전달 계층 대체 — 격리 검증 대상은 LLM payload 이므로 결과만 기록한다."""

    def __init__(self):
        self.answers: list[tuple[str, str]] = []  # (channel_id, answer)

    def open_stream(self, request):
        return _NullSink()

    async def deliver_answer(self, *, binding, request, completion, chat_job_id):
        self.answers.append((request.channel_id, completion.answer))
        return True

    async def deliver_error(self, *, request, text=""):
        return True


class _FixedBindingReader:
    def __init__(self, binding):
        self._b = binding

    def get_binding(self, channel_id):
        return self._b


_SECRET_A = "A-채널-비밀대화-토큰-XYZ"


async def test_ch_002_channel_a_history_absent_from_channel_b_llm_payload(embedding, reranker):
    store = _FakeStore()
    binding_a = make_binding(CHANNEL_A)
    binding_b = make_binding(CHANNEL_B)
    # A 채널에 민감한 대화를 심는다
    store.seed(scope_key(binding_a, None, "p"), "user", _SECRET_A)

    qdrant = InMemoryQdrant([make_payload("y", [CHANNEL_B], "B 근거", title="Y")])
    llm = CapturingLLM()
    deps = WorkerDeps(
        binding_reader=_FixedBindingReader(binding_b),
        store=store,
        pipeline=_pipeline(qdrant, embedding, reranker, llm),
        delivery=_FakeDelivery(),
    )
    await process_chat_job(deps, "job-b", make_request(CHANNEL_B, "B 질문"))

    joined = "".join(m["content"] for m in llm.messages)
    assert _SECRET_A not in joined  # A의 대화가 B의 LLM Context에 없다


async def test_ch_003_same_user_two_channels_context_independent(embedding, reranker):
    store = _FakeStore()
    binding_a = make_binding(CHANNEL_A)
    binding_b = make_binding(CHANNEL_B)
    store.seed(scope_key(binding_a, None, "p"), "user", _SECRET_A)

    # 동일 사용자가 B에서 질문 → A scope_key와 다른 conversation
    sk_b = scope_key(binding_b, None, "post-channel-B")
    assert sk_b != scope_key(binding_a, None, "p")
    assert store.load_history(sk_b, 16) == []  # B 대화는 비어 있음


# ---------------------------------------------------------------------------
# CH-004: 지식범위 category 격리
# ---------------------------------------------------------------------------
async def test_ch_004_category_scope_excludes_other_category(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("ops", [CHANNEL_A], "운영 문서", category="운영매뉴얼", title="OPS"),
            make_payload("hr", [CHANNEL_A], "인사 문서", category="인사규정", title="HR"),
        ]
    )
    llm = CapturingLLM()
    binding = make_binding(CHANNEL_A, categories=["운영매뉴얼"])
    out = await _run(binding, "질문", qdrant, embedding, reranker, llm)
    titles = {c.document_name for c in out.citations}
    assert titles == {"OPS"}  # 범위 밖 category 제외


# ---------------------------------------------------------------------------
# CH-005: 미등록 Channel — 파이프라인 실행 없음 (binding None)
# ---------------------------------------------------------------------------
async def test_ch_005_unbound_channel_never_runs_pipeline(embedding, reranker):
    llm = CapturingLLM()
    deps = WorkerDeps(
        binding_reader=_FixedBindingReader(None),
        store=_FakeStore(),
        pipeline=_pipeline(InMemoryQdrant([]), embedding, reranker, llm),
        delivery=_FakeDelivery(),
    )
    with pytest.raises(RuntimeError):
        await process_chat_job(deps, "job-x", make_request("unregistered", "질문"))
    assert llm.messages == []  # LLM 절대 미호출


# ---------------------------------------------------------------------------
# CH-006: department 격리
# ---------------------------------------------------------------------------
async def test_ch_006_department_scope_excludes_other_department(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("cloud", [CHANNEL_A], "클라우드", department="Cloud운영팀", title="CLOUD"),
            make_payload("hr", [CHANNEL_A], "인사", department="인사팀", title="HR"),
        ]
    )
    llm = CapturingLLM()
    binding = make_binding(CHANNEL_A, departments=["Cloud운영팀"])
    out = await _run(binding, "질문", qdrant, embedding, reranker, llm)
    assert {c.document_name for c in out.citations} == {"CLOUD"}


# ---------------------------------------------------------------------------
# CH-007: security_level 격리
# ---------------------------------------------------------------------------
async def test_ch_007_security_level_excludes_confidential(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("i", [CHANNEL_A], "내부", security_level="INTERNAL", title="INT"),
            make_payload("c", [CHANNEL_A], "기밀", security_level="CONFIDENTIAL", title="CONF"),
        ]
    )
    llm = CapturingLLM()
    binding = make_binding(CHANNEL_A, security_levels=["INTERNAL"])
    out = await _run(binding, "질문", qdrant, embedding, reranker, llm)
    assert {c.document_name for c in out.citations} == {"INT"}


async def test_ch_007_unscoped_channel_sees_all_levels_of_own_acl_only(embedding, reranker):
    """지식 범위 미지정 채널: 보안등급과 무관하게 자기 채널에 연결된 문서만 — 다른 채널 문서는 여전히 차단."""
    qdrant = InMemoryQdrant(
        [
            make_payload("p", [CHANNEL_A], "공개", security_level="PUBLIC", title="PUB"),
            make_payload("i", [CHANNEL_A], "내부", security_level="INTERNAL", title="INT"),
            make_payload("b", [CHANNEL_B], "타채널", security_level="PUBLIC", title="OTHER"),
        ]
    )
    llm = CapturingLLM()
    out = await _run(make_binding(CHANNEL_A), "질문", qdrant, embedding, reranker, llm)
    assert {c.document_name for c in out.citations} == {"PUB", "INT"}
    assert "타채널" not in "".join(m["content"] for m in llm.messages)


# ---------------------------------------------------------------------------
# CH-008: 비활성(is_active=false) 문서 제외 (삭제/재색인)
# ---------------------------------------------------------------------------
async def test_ch_008_inactive_document_excluded(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("live", [CHANNEL_A], "현행", is_active=True, title="LIVE"),
            make_payload("old", [CHANNEL_A], "구버전", is_active=False, title="OLD"),
        ]
    )
    llm = CapturingLLM()
    out = await _run(make_binding(CHANNEL_A), "질문", qdrant, embedding, reranker, llm)
    assert {c.document_name for c in out.citations} == {"LIVE"}


# ---------------------------------------------------------------------------
# CH-009: 명시 document_ids 범위
# ---------------------------------------------------------------------------
async def test_ch_009_explicit_document_ids_scope(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("a", [CHANNEL_A], "문서 A", document_id="doc-allowed", title="A"),
            make_payload("b", [CHANNEL_A], "문서 B", document_id="doc-other", title="B"),
        ]
    )
    binding = make_binding(CHANNEL_A)
    binding.knowledge_scope.document_ids = ["doc-allowed"]
    llm = CapturingLLM()
    out = await _run(binding, "질문", qdrant, embedding, reranker, llm)
    assert {c.document_name for c in out.citations} == {"A"}


# ---------------------------------------------------------------------------
# 답변 payload 무결성: 완성된 RagCompletion에도 타 Channel 텍스트 부재
# ---------------------------------------------------------------------------
async def test_ch_answer_contains_no_foreign_channel_text(embedding, reranker):
    qdrant = InMemoryQdrant(
        [
            make_payload("x", [CHANNEL_A], "A근거", title="X"),
            make_payload("secret", [CHANNEL_B], "타채널기밀문자열", title="SECRET"),
        ]
    )
    llm = CapturingLLM()
    out = await _run(make_binding(CHANNEL_A), "질문", qdrant, embedding, reranker, llm)
    completion = RagCompletion(message_id="m", answer=out.answer, citations=out.citations)
    assert "타채널기밀문자열" not in completion.model_dump_json()

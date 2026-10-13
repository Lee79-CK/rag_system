"""M6 통합 테스트: 질문 → (fake embed/search/rerank/stream LLM) → 스트리밍 + Bot Post 갱신 검증.

§7.2 파이프라인 + §7.2.5 답변 blocks(근거 문서 table) + 피드백 토큰 포함을 assert한다 (M6 DoD).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from chat_adapter import PostRow, StreamEmitter, verify_feedback_token
from rag.adapters.webchat_delivery import DeliveryDeps, WebChatDelivery
from rag.domain.pipeline import PipelineConfig, RagPipeline
from rag.domain.ports import LLMResult, LLMStreamEvent, RetrievedChunk
from rag.domain.tokens import HeuristicTokenCounter
from rag.worker.chat_worker import CHANNEL_DISABLED_TEXT, WorkerDeps, process_chat_job
from rag_schemas import ChannelBinding, ChannelMode, ChatRequest, KnowledgeScope, QdrantChunkPayload
from rag_schemas.webchat import UserBrief

SIGNING_KEY = b"test-signing-key"
ANSWER_TOKENS = ["장애 등급은 ", "1~4등급", "입니다. [1]"]


# ---- Fakes ----
class FakeEmbedding:
    async def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


class FakeRetrieval:
    def __init__(self, payloads):
        self._payloads = payloads

    async def search(self, query_vector, qdrant_filter, top_k):
        return [
            RetrievedChunk(payload=p, score=0.9 - i * 0.01) for i, p in enumerate(self._payloads)
        ]


class FakeRerank:
    async def rerank(self, query, documents, top_n):
        return [(i, 0.9 - i * 0.01) for i in range(min(top_n, len(documents)))]


class FakeLLM:
    def __init__(self, fail: bool = False):
        self.calls = 0
        self.stream_calls = 0
        self.fail = fail

    async def complete(self, messages, *, max_tokens, temperature):
        self.calls += 1
        return LLMResult(text="".join(ANSWER_TOKENS), usage={"prompt_tokens": 10})

    async def stream(self, messages, *, max_tokens, temperature):
        self.stream_calls += 1
        if self.fail:
            raise ConnectionError("vllm down")
        for tok in ANSWER_TOKENS:
            yield LLMStreamEvent(delta=tok)
        yield LLMStreamEvent(usage={"prompt_tokens": 10, "completion_tokens": 3})


class FakeStore:
    def __init__(self):
        self.messages: dict[str, list[tuple[str, str]]] = {}
        self.jobs: dict[str, str] = {}
        self.assistant_id = "assistant-msg-1"
        self.assistant_post_id: str | None = None

    def upsert_conversation(self, *, scope_key, channel_id, root_id, mode):
        self.messages.setdefault(scope_key, [])
        return scope_key

    def load_history(self, conversation_id, limit):
        return list(self.messages.get(conversation_id, []))[-limit:]

    def add_user_message(self, conversation_id, post_id, content):
        self.messages.setdefault(conversation_id, []).append(("user", content))
        return "user-msg-1"

    def add_assistant_message(self, conversation_id, content, *, post_id, latency_ms, citations):
        self.messages.setdefault(conversation_id, []).append(("assistant", content))
        self.citations = citations
        self.assistant_post_id = post_id
        return self.assistant_id

    def claim_job(self, job_id):
        if self.jobs.get(job_id) not in (None, "QUEUED"):
            return False
        self.jobs[job_id] = "RUNNING"
        return True

    def update_job_status(self, job_id, status, *, error=None, mark_started=False):
        self.jobs[job_id] = status


class FakePosts:
    """chat_posts placeholder 갱신 캡처."""

    def __init__(self):
        self.updates: list[dict] = []

    def update_bot_post(self, post_id, *, message, blocks, props):
        self.updates.append(
            {"post_id": post_id, "message": message, "blocks": blocks, "props": props}
        )
        return PostRow(
            id=post_id,
            channel_id="channel-001",
            root_id=None,
            type="bot",
            message=message,
            blocks=blocks,
            props=props,
            created_at=datetime.now(UTC),
            user=UserBrief(id="bot", display_name="RAG Assistant", is_bot=True),
        )


class SpyManager:
    def __init__(self):
        self.events: list[tuple[str, dict, str | None]] = []

    async def emit(self, event, data, namespace=None, room=None, **kw):
        self.events.append((event, data, room))


class FakeBindingReader:
    def __init__(self, binding):
        self._b = binding

    def get_binding(self, channel_id):
        return self._b


@pytest.fixture
def binding():
    return ChannelBinding(
        id="b1",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=True,
        knowledge_scope=KnowledgeScope(categories=["장애대응"]),
        feedback_enabled=True,
    )


def _payload():
    return QdrantChunkPayload(
        document_id="f0",
        document_version_id="v1",
        chunk_id="v1-00012",
        title="장애대응매뉴얼",
        source_file="/data/x.pdf",
        page_start=12,
        section="3.2",
        chunk_index=12,
        allowed_channel_ids=["channel-001"],
        content_hash="sha256:x",
        text="장애 등급별 대응 절차 ...",
    )


def _pipeline(llm, retrieval=None, **cfg):
    return RagPipeline(
        embedding=FakeEmbedding(),
        retrieval=retrieval or FakeRetrieval([_payload()]),
        reranker=FakeRerank(),
        llm=llm,
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(
            **{"similarity_threshold": 0.0, "rerank_score_threshold": 0.0, **cfg}
        ),
    )


def _request(**over) -> ChatRequest:
    base = {
        "source": "web",
        "channel_id": "channel-001",
        "user_id": "user-001",
        "user_name": "honggildong",
        "post_id": "post-1",
        "root_id": None,
        "bot_post_id": "bot-post-1",
        "message": "장애 등급별 대응 절차를 알려주세요.",
        "trace_id": "trace-1",
    }
    base.update(over)
    return ChatRequest(**base)


def _deps(binding, llm, **kw):
    posts, spy, store = FakePosts(), SpyManager(), FakeStore()
    delivery = WebChatDelivery(
        DeliveryDeps(posts=posts, emitter=StreamEmitter(spy), signing_key=SIGNING_KEY)
    )
    deps = WorkerDeps(
        binding_reader=FakeBindingReader(binding),
        store=store,
        pipeline=_pipeline(llm, **kw),
        delivery=delivery,
    )
    return deps, store, posts, spy


async def test_full_pipeline_streams_and_updates_bot_post(binding):
    llm = FakeLLM()
    deps, store, posts, spy = _deps(binding, llm)

    completion = await process_chat_job(deps, "job-1", _request())

    # LLM 은 스트리밍으로만 호출되었다 (complete 미사용)
    assert llm.stream_calls == 1 and llm.calls == 0
    assert store.jobs["job-1"] == "COMPLETED"

    # 스트리밍 delta 는 채널 room 으로, 누적 = 최종 답변
    deltas = [e for e in spy.events if e[0] == "llm.stream.delta"]
    assert deltas and all(e[2] == "channel:channel-001" for e in deltas)
    assert "".join(e[1]["delta"] for e in deltas) == "".join(ANSWER_TOKENS)
    assert all(e[1]["post_id"] == "bot-post-1" for e in deltas)
    # 이벤트 순서: delta... → post.updated → llm.stream.end
    assert [e[0] for e in spy.events][-2:] == ["post.updated", "llm.stream.end"]

    # Bot Post 최종 갱신: mention + 근거 문서 table + 피드백 토큰
    upd = posts.updates[0]
    assert upd["post_id"] == "bot-post-1"
    assert upd["message"].startswith("@honggildong ")
    assert upd["blocks"][0]["type"] == "table"
    assert upd["blocks"][0]["rows"][0]["doc"] == "장애대응매뉴얼"
    assert upd["props"]["streaming"] is False and upd["props"]["kind"] == "answer"
    # 피드백 토큰 = HMAC(message_id:bot_post_id) — 저장된 assistant message 와 결합
    assert store.assistant_post_id == "bot-post-1"
    assert verify_feedback_token(
        SIGNING_KEY, "assistant-msg-1", "bot-post-1", upd["props"]["feedback_token"]
    )
    # message_id 는 클라이언트 이벤트에 노출되지 않는다
    updated_evt = next(e for e in spy.events if e[0] == "post.updated")
    assert "message_id" not in updated_evt[1]["props"]
    assert completion.citations[0].document_name == "장애대응매뉴얼"


async def test_feedback_disabled_channel_has_no_token(binding):
    binding.feedback_enabled = False
    deps, _, posts, _ = _deps(binding, FakeLLM())
    await process_chat_job(deps, "job-1", _request())
    assert "feedback_token" not in posts.updates[0]["props"]


async def test_insufficient_evidence_skips_llm(binding):
    class EmptyRetrieval:
        async def search(self, *a, **k):
            return []

    llm = FakeLLM()
    deps, _, posts, spy = _deps(binding, llm, retrieval=EmptyRetrieval(), similarity_threshold=0.5)

    completion = await process_chat_job(deps, "job-2", _request(message="문서에 없는 질문"))
    assert llm.calls == 0 and llm.stream_calls == 0
    assert completion.insufficient_evidence is True
    assert "근거를 찾지 못했습니다" in completion.answer
    assert not [e for e in spy.events if e[0] == "llm.stream.delta"]
    assert posts.updates[0]["blocks"][-1]["type"] == "context"


async def test_pipeline_failure_marks_bot_post_error(binding):
    deps, store, posts, spy = _deps(binding, FakeLLM(fail=True))
    with pytest.raises(ConnectionError):
        await process_chat_job(deps, "job-3", _request())
    assert store.jobs["job-3"] == "FAILED"
    assert posts.updates[0]["props"] == {"streaming": False, "kind": "error"}
    assert spy.events[-1][0] == "llm.stream.end"


async def test_disabled_binding_updates_placeholder(binding):
    binding.enabled = False
    llm = FakeLLM()
    deps, store, posts, _ = _deps(binding, llm)
    with pytest.raises(RuntimeError):
        await process_chat_job(deps, "job-4", _request())
    assert store.jobs["job-4"] == "FAILED"
    assert posts.updates[0]["message"] == CHANNEL_DISABLED_TEXT
    assert llm.stream_calls == 0


async def test_stream_emit_failure_does_not_abort_answer(binding):
    class BrokenOnDelta(SpyManager):
        async def emit(self, event, data, namespace=None, room=None, **kw):
            if event == "llm.stream.delta":
                raise ConnectionError("redis pubsub down")
            await super().emit(event, data, namespace, room, **kw)

    posts, spy, store = FakePosts(), BrokenOnDelta(), FakeStore()
    deps = WorkerDeps(
        binding_reader=FakeBindingReader(binding),
        store=store,
        pipeline=_pipeline(FakeLLM()),
        delivery=WebChatDelivery(
            DeliveryDeps(posts=posts, emitter=StreamEmitter(spy), signing_key=SIGNING_KEY)
        ),
    )
    await process_chat_job(deps, "job-5", _request())
    assert store.jobs["job-5"] == "COMPLETED"  # 최종 Post 갱신(SSOT) 은 성공
    assert posts.updates[0]["message"].endswith("[1]")


async def test_worker_skips_already_claimed_job(binding):
    """RQ 재실행/중복 enqueue 로 같은 job 이 다시 들어오면 LLM·Bot Post 갱신·스트림 emit 없이 종료 (멱등, 리뷰 H-4)."""
    llm = FakeLLM()
    deps, store, posts, spy = _deps(binding, llm)
    store.jobs["job-dup"] = "COMPLETED"  # 이미 처리된 job
    result = await process_chat_job(deps, "job-dup", _request())
    assert result is None
    assert llm.stream_calls == 0 and llm.calls == 0
    assert posts.updates == [] and spy.events == []
    assert store.jobs["job-dup"] == "COMPLETED"  # 상태 미변경


async def test_missing_signing_key_attaches_no_feedback_token(binding):
    """서명키가 비면 피드백 토큰을 만들지 않는다 (빈 키 HMAC 금지 — fail-closed)."""
    posts, spy, store = FakePosts(), SpyManager(), FakeStore()
    deps = WorkerDeps(
        binding_reader=FakeBindingReader(binding),
        store=store,
        pipeline=_pipeline(FakeLLM()),
        delivery=WebChatDelivery(
            DeliveryDeps(posts=posts, emitter=StreamEmitter(spy), signing_key=b"")
        ),
    )
    await process_chat_job(deps, "job-6", _request())
    assert store.jobs["job-6"] == "COMPLETED"
    assert "feedback_token" not in posts.updates[0]["props"]


# ---------------------------------------------------------------- FR-CHAT-014 LLM 직접 대화
class _MustNotCall:
    """직접 대화에서 호출되면 안 되는 검색 계층 (embed/search/rerank)."""

    async def embed(self, *a, **k):
        raise AssertionError("embedding called in direct mode")

    async def search(self, *a, **k):
        raise AssertionError("qdrant search called in direct mode")

    async def rerank(self, *a, **k):
        raise AssertionError("rerank called in direct mode")


class _CapturingLLM(FakeLLM):
    def __init__(self):
        super().__init__()
        self.messages = None

    async def stream(self, messages, *, max_tokens, temperature):
        self.messages = messages
        async for ev in super().stream(messages, max_tokens=max_tokens, temperature=temperature):
            yield ev


def _direct_deps(binding, llm):
    deps, store, posts, spy = _deps(binding, llm)
    blocked = _MustNotCall()
    deps.pipeline = RagPipeline(
        embedding=blocked,
        retrieval=blocked,
        reranker=blocked,
        llm=llm,
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(),
    )
    return deps, store, posts, spy


async def test_fr_chat_014_direct_skips_retrieval_and_streams(binding):
    binding.direct_llm_enabled = True
    llm = _CapturingLLM()
    deps, store, posts, spy = _direct_deps(binding, llm)
    # 같은 conversation(채널 컨텍스트)의 이전 RAG 대화 — 직접 대화도 이력을 공유한다
    store.messages["channel-001"] = [("user", "장애 등급은?"), ("assistant", "1~4등급입니다. [1]")]

    completion = await process_chat_job(
        deps, "job-d", _request(message="이걸 영어로 번역해줘", direct=True)
    )

    assert completion.direct is True and completion.citations == []
    assert completion.insufficient_evidence is False and completion.usage["direct"] == 1
    assert store.jobs["job-d"] == "COMPLETED"
    # 네이티브 chat 형식: system → 이력(user/assistant) → 질문
    assert [m["role"] for m in llm.messages] == ["system", "user", "assistant", "user"]
    assert "사내 문서를 검색하지 않습니다" in llm.messages[0]["content"]
    assert llm.messages[-1]["content"] == "이걸 영어로 번역해줘"
    deltas = [e for e in spy.events if e[0] == "llm.stream.delta"]
    assert "".join(e[1]["delta"] for e in deltas) == "".join(ANSWER_TOKENS)
    # Bot Post: 근거 표 없이 직접 대화 안내 + props.direct + 피드백 토큰 유지
    upd = posts.updates[0]
    assert [b["block_id"] for b in upd["blocks"]] == ["direct"]
    assert upd["props"]["direct"] is True and "feedback_token" in upd["props"]
    assert store.citations == []


async def test_fr_chat_014_direct_request_on_disabled_channel_uses_rag(binding):
    """enqueue 이후 채널 설정이 꺼졌으면 직접 대화가 아니라 RAG 로 처리한다."""
    llm = FakeLLM()
    deps, _, posts, _ = _deps(binding, llm)  # binding.direct_llm_enabled 기본 False

    completion = await process_chat_job(deps, "job-r", _request(direct=True))

    assert completion.direct is False
    assert completion.citations and posts.updates[0]["blocks"][0]["type"] == "table"
    assert posts.updates[0]["props"]["direct"] is False

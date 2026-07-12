"""M6 통합 테스트: 질문 → (fake embed/search/rerank/mock LLM) → 게시 payload 검증.

§7.2 파이프라인 + §7.2.5 피드백 버튼 attachment 포함을 assert한다 (M6 DoD).
"""

from __future__ import annotations

import pytest
from rag.adapters.delivery_adapter import DeliveryDeps, MattermostDelivery
from rag.domain.pipeline import PipelineConfig, RagPipeline
from rag.domain.ports import LLMResult, RetrievedChunk
from rag.domain.tokens import HeuristicTokenCounter
from rag.worker.chat_worker import WorkerDeps, process_chat_job
from rag_schemas import ChannelBinding, ChannelMode, ChatRequest, KnowledgeScope, QdrantChunkPayload


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
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, *, max_tokens, temperature):
        self.calls += 1
        return LLMResult(text="장애 등급은 1~4등급입니다. [1]", usage={"prompt_tokens": 10})


class FakeStore:
    def __init__(self):
        self.messages: dict[str, list[tuple[str, str]]] = {}
        self.jobs: dict[str, str] = {}
        self.deliveries: list[dict] = []
        self.assistant_id = "assistant-msg-1"

    def upsert_conversation(self, *, scope_key, team_id, channel_id, root_id, mode):
        self.messages.setdefault(scope_key, [])
        return scope_key

    def load_history(self, conversation_id, limit):
        return list(self.messages.get(conversation_id, []))[-limit:]

    def add_user_message(self, conversation_id, post_id, content):
        self.messages.setdefault(conversation_id, []).append(("user", content))
        return "user-msg-1"

    def add_assistant_message(self, conversation_id, content, *, latency_ms, citations):
        self.messages.setdefault(conversation_id, []).append(("assistant", content))
        self.citations = citations
        return self.assistant_id

    def update_job_status(self, job_id, status, *, error=None, mark_started=False):
        self.jobs[job_id] = status

    def record_delivery(self, job_id, channel_id, *, attempt, status, http_status):
        self.deliveries.append({"status": status, "http": http_status})


class FakeBindingReader:
    def __init__(self, binding):
        self._b = binding

    def get_binding(self, team_id, channel_id):
        return self._b


@pytest.fixture
def binding():
    return ChannelBinding(
        id="b1",
        team_id="team-001",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=True,
        knowledge_scope=KnowledgeScope(categories=["장애대응"]),
        incoming_webhook_secret_ref="mattermost-incoming-rag-cloud-ops",
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


def _pipeline(llm):
    return RagPipeline(
        embedding=FakeEmbedding(),
        retrieval=FakeRetrieval([_payload()]),
        reranker=FakeRerank(),
        llm=llm,
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(similarity_threshold=0.0, rerank_score_threshold=0.0),
    )


async def test_full_pipeline_delivers_answer_with_feedback_attachment(
    binding, tmp_path, monkeypatch
):
    # secret_ref 파일에 Incoming Webhook URL 배치 (실제 게시는 monkeypatch로 캡처)
    (tmp_path / binding.incoming_webhook_secret_ref).write_text("https://mm/hooks/xyz")

    captured: list = []

    async def fake_deliver(url, message, *, secret_ref, config=None, client=None):
        from mattermost_adapter.delivery import DeliveryResult

        captured.append({"url": url, "message": message, "secret_ref": secret_ref})
        return DeliveryResult(ok=True, attempts=1, http_status=200, posted_parts=1)

    monkeypatch.setattr("rag.adapters.delivery_adapter.deliver", fake_deliver)

    delivery = MattermostDelivery(
        DeliveryDeps(
            secret_dir=str(tmp_path),
            signing_key=b"test-signing-key",
            action_url="http://bridge/integrations/mattermost/v1/actions",
        )
    )
    store = FakeStore()
    llm = FakeLLM()
    deps = WorkerDeps(
        binding_reader=FakeBindingReader(binding),
        store=store,
        pipeline=_pipeline(llm),
        delivery=delivery,
    )
    request = ChatRequest(
        source="mattermost",
        team_id="team-001",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        user_id="mmuser-001",
        user_name="honggildong",
        post_id="post-1",
        root_id=None,
        message="장애 등급별 대응 절차를 알려주세요.",
        trace_id="trace-1",
    )

    completion = await process_chat_job(deps, "job-1", request)

    # LLM이 호출되었고 답변이 게시되었다
    assert llm.calls == 1
    assert store.jobs["job-1"] == "COMPLETED"
    assert len(captured) == 1
    msg = captured[0]["message"]

    # 게시 payload: mention + 근거 문서 + 피드백 버튼 attachment
    assert "@honggildong" in msg.text
    assert "장애대응매뉴얼" in msg.text
    assert len(msg.attachments) == 1
    actions = msg.attachments[0]["actions"]
    assert {a["id"] for a in actions} == {"fb_up", "fb_down"}
    # 버튼 context의 message_id는 저장된 assistant 메시지 id
    assert actions[0]["integration"]["context"]["message_id"] == "assistant-msg-1"
    # URL은 반환 결과(secret_ref)로만 노출, completion에는 없음
    assert completion.message_id == "assistant-msg-1"
    assert completion.citations[0].document_name == "장애대응매뉴얼"


async def test_insufficient_evidence_skips_llm(binding, tmp_path, monkeypatch):
    (tmp_path / binding.incoming_webhook_secret_ref).write_text("https://mm/hooks/xyz")

    async def fake_deliver(url, message, *, secret_ref, config=None, client=None):
        from mattermost_adapter.delivery import DeliveryResult

        fake_deliver.msg = message
        return DeliveryResult(ok=True, attempts=1, http_status=200, posted_parts=1)

    monkeypatch.setattr("rag.adapters.delivery_adapter.deliver", fake_deliver)

    # 검색 0건 → 근거 부족 → LLM 미호출
    class EmptyRetrieval:
        async def search(self, *a, **k):
            return []

    llm = FakeLLM()
    pipeline = RagPipeline(
        embedding=FakeEmbedding(),
        retrieval=EmptyRetrieval(),
        reranker=FakeRerank(),
        llm=llm,
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(similarity_threshold=0.5),
    )
    delivery = MattermostDelivery(
        DeliveryDeps(secret_dir=str(tmp_path), signing_key=b"k", action_url="http://bridge/actions")
    )
    deps = WorkerDeps(
        binding_reader=FakeBindingReader(binding),
        store=FakeStore(),
        pipeline=pipeline,
        delivery=delivery,
    )
    request = ChatRequest(
        source="mattermost",
        team_id="team-001",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        user_id="u",
        user_name="un",
        post_id="p",
        root_id=None,
        message="문서에 없는 질문",
        trace_id="t",
    )

    completion = await process_chat_job(deps, "job-2", request)
    assert llm.calls == 0
    assert completion.insufficient_evidence is True
    assert "근거를 찾지 못했습니다" in completion.answer

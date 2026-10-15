"""평가셋 후보 승격·관리·내보내기 — TDD §7.5, §13.3 (FR-OPS-012)."""

from __future__ import annotations

import contextlib
import datetime
import json
import uuid

import httpx
import yaml
from admin.db.models import (
    ChannelConversation,
    ChatChannel,
    ChatJob,
    ChatPost,
    Citation,
    Document,
    EvaluationRun,
    Message,
    MessageFeedbackRow,
)
from admin.services.eval_runner import EvalRunner, HttpRagCompletions, provide_eval_runner

CHANNEL = "5a4f17e3-bb99-46b2-9fd4-16b89caaa641"


def _seed_down_answer(TestSession, *, question="HYBE 2025년 총 매출은?") -> str:
    """질문 Post → chat_job → 답변(Bot Post) + 👎 + 인용 문서 1건."""
    with TestSession() as s:
        ch = ChatChannel(id=uuid.UUID(CHANNEL), name="entertainment", display_name="엔터")
        conv = ChannelConversation(scope_key=CHANNEL, channel_id=CHANNEL, mode="CHANNEL")
        s.add_all([ch, conv])
        s.flush()
        q_post = ChatPost(channel_id=ch.id, type="user", message=f"!rag {question}")
        b_post = ChatPost(channel_id=ch.id, type="bot", message="답변")
        s.add_all([q_post, b_post])
        s.flush()
        s.add(ChatJob(post_id=q_post.id, bot_post_id=b_post.id, conversation_id=conv.id))
        s.add(Message(conversation_id=conv.id, post_id=q_post.id, role="user", content=question))
        answer = Message(
            conversation_id=conv.id,
            post_id=b_post.id,
            role="assistant",
            content="명시되어 있지 않습니다. [1]",
        )
        doc = Document(title="HYBE_IR_2025.pdf")
        s.add_all([answer, doc])
        s.flush()
        s.add(Citation(message_id=answer.id, chunk_id="v1-00001", document_id=doc.id, rank=1))
        s.add(
            MessageFeedbackRow(message_id=answer.id, user_id="u1", value="DOWN", channel_id=CHANNEL)
        )
        s.commit()
        return str(answer.id)


def test_fr_ops_012_promote_snapshots_question_answer_and_is_idempotent(
    client, TestSession, seed, auth
):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    mid = _seed_down_answer(TestSession)

    first = client.post(
        "/api/v1/evaluation/candidates", json={"message_id": mid}, headers=auth("evaluator")
    )
    assert first.status_code == 201, first.text
    assert first.json()["data"]["status"] == "PENDING" and first.json()["data"]["created"] is True
    again = client.post(
        "/api/v1/evaluation/candidates", json={"message_id": mid}, headers=auth("evaluator")
    )
    assert again.status_code == 200 and again.json()["data"]["created"] is False
    assert again.json()["data"]["candidate_id"] == first.json()["data"]["candidate_id"]

    rows = client.get("/api/v1/evaluation/candidates", headers=auth("evaluator")).json()["data"]
    assert len(rows) == 1
    c = rows[0]
    # 질문은 chat_jobs 로 연결된 user message(트리거어 제거된 원문)
    assert c["question"] == "HYBE 2025년 총 매출은?"
    assert c["answer"] == "명시되어 있지 않습니다. [1]"
    assert c["channel_id"] == CHANNEL and c["promoted_by"] == "evaluator"
    assert c["cited_documents"] == ["HYBE_IR_2025.pdf"] == c["expected_documents"]

    # 👎 목록에 질문·승격 상태가 함께 나온다
    fb = client.get("/api/v1/feedback/messages", headers=auth("evaluator")).json()["data"][0]
    assert fb["question"] == "HYBE 2025년 총 매출은?" and fb["candidate_status"] == "PENDING"


def test_fr_ops_012_promote_rejects_unknown_or_user_message(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"], "doc": ["DOC_ADMIN"]})
    _seed_down_answer(TestSession)
    missing = client.post(
        "/api/v1/evaluation/candidates",
        json={"message_id": str(uuid.uuid4())},
        headers=auth("evaluator"),
    )
    assert missing.status_code == 404
    with TestSession() as s:
        from sqlalchemy import select

        user_mid = s.execute(select(Message.id).where(Message.role == "user")).scalar_one()
    bad = client.post(
        "/api/v1/evaluation/candidates",
        json={"message_id": str(user_mid)},
        headers=auth("evaluator"),
    )
    assert bad.status_code == 422
    # 문서 관리자는 평가 기능 접근 불가
    assert client.get("/api/v1/evaluation/candidates", headers=auth("doc")).status_code == 403


def test_fr_ops_012_accept_requires_gist_and_exports_runner_yaml(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    mid = _seed_down_answer(TestSession, question='따옴표 "테스트"\n두 줄')
    cid = client.post(
        "/api/v1/evaluation/candidates", json={"message_id": mid}, headers=auth("evaluator")
    ).json()["data"]["candidate_id"]
    url = f"/api/v1/evaluation/candidates/{cid}"

    no_gist = client.patch(url, json={"status": "ACCEPTED"}, headers=auth("evaluator"))
    assert no_gist.status_code == 422
    ok = client.patch(
        url,
        json={
            "status": "ACCEPTED",
            "case_type": "table",
            "answer_gist": "분기 합계 약 2.6조",
            "expected_pages": [3, 4],
        },
        headers=auth("evaluator"),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["case_type"] == "table"

    exp = client.get("/api/v1/evaluation/candidates/export", headers=auth("evaluator"))
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    cases = yaml.safe_load(exp.text)
    assert cases == [
        {
            "id": f"fb-{cid[:8]}",
            "type": "table",
            "question": '따옴표 "테스트"\n두 줄',
            "channel_id": CHANNEL,
            "ground_truth": {
                "answer_gist": "분기 합계 약 2.6조",
                "documents": ["HYBE_IR_2025.pdf"],
                "pages": [3, 4],
                "answerable": True,
            },
        }
    ]
    # 제외(REJECTED)하면 내보내기에서 빠진다
    client.patch(url, json={"status": "REJECTED"}, headers=auth("evaluator"))
    assert (
        yaml.safe_load(
            client.get("/api/v1/evaluation/candidates/export", headers=auth("evaluator")).text
        )
        is None
    )


# ---------------------------------------------------------------- 포털 평가 실행 (FR-OPS-008)


def _accept(client, auth, mid: str, **over) -> str:
    cid = client.post(
        "/api/v1/evaluation/candidates", json={"message_id": mid}, headers=auth("evaluator")
    ).json()["data"]["candidate_id"]
    body = {"status": "ACCEPTED", "answer_gist": "요지", **over}
    assert (
        client.patch(
            f"/api/v1/evaluation/candidates/{cid}", json=body, headers=auth("evaluator")
        ).status_code
        == 200
    )
    return cid


def _use_rag(client, TestSession, handler) -> list[dict]:
    """rag-api completions 를 MockTransport 로 대체하고 받은 요청 본문을 기록한다."""
    calls: list[dict] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        return handler(body)

    @contextlib.contextmanager
    def _factory():
        with httpx.Client(base_url="http://rag-api", transport=httpx.MockTransport(_handle)) as c:
            yield HttpRagCompletions(c)

    client.app.dependency_overrides[provide_eval_runner] = lambda: EvalRunner(TestSession, _factory)
    return calls


def _completion(answer: str, cited: list[str], retrieved: list[str], insufficient=False) -> dict:
    doc = lambda n: {"document_id": "d", "document_name": n, "excerpt": "", "chunk_id": "c"}  # noqa: E731
    return {
        "message_id": "",
        "answer": answer,
        "citations": [doc(n) for n in cited],
        "retrieved": [doc(n) for n in retrieved],
        "insufficient_evidence": insufficient,
    }


def test_fr_ops_008_run_evaluates_accepted_candidates_and_stores_results(
    client, TestSession, seed, auth
):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    mid = _seed_down_answer(TestSession)
    _accept(client, auth, mid)
    # 인용은 다른 문서지만 검색(retrieved)에는 정답 문서가 있다 → Recall 1.0, Citation Precision 0.0
    calls = _use_rag(
        client,
        TestSession,
        lambda b: httpx.Response(
            200, json=_completion("답 [2]", ["기타.pdf"], ["HYBE_IR_2025.pdf", "기타.pdf"])
        ),
    )

    started = client.post("/api/v1/evaluation/runs", headers=auth("evaluator"))
    assert started.status_code == 202, started.text
    run_id = started.json()["data"]["id"]
    assert calls == [{"channel_id": CHANNEL, "message": "HYBE 2025년 총 매출은?"}]

    runs = client.get("/api/v1/evaluation/runs", headers=auth("evaluator")).json()["data"]
    assert runs[0]["id"] == run_id and runs[0]["status"] == "COMPLETED"
    assert runs[0]["done"] == runs[0]["total"] == 1 and runs[0]["started_by"] == "evaluator"
    m = runs[0]["metrics"]
    assert m["total"] == 1 and m["recall_at_10"] == 1.0 and m["citation_precision"] == 0.0
    assert m["answerable_answered"] == 1.0
    assert m["applicable"] == {
        "recall_at_10": 1,
        "citation_precision": 1,
        "no_answer_safety": 0,
        "answerable_answered": 1,
    }

    detail = client.get(f"/api/v1/evaluation/runs/{run_id}", headers=auth("evaluator")).json()[
        "data"
    ]
    r = detail["results"][0]
    assert r["question"] == "HYBE 2025년 총 매출은?" and r["answer"] == "답 [2]"
    assert r["retrieved"] == ["HYBE_IR_2025.pdf", "기타.pdf"] and r["citations"] == ["기타.pdf"]
    assert (
        r["recall_at_10"] == 1.0 and r["citation_precision"] == 0.0 and r["no_answer_safe"] is None
    )
    assert r["error"] is None


def test_fr_ops_008_case_failure_is_recorded_and_run_completes(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    _accept(client, auth, _seed_down_answer(TestSession))
    _use_rag(client, TestSession, lambda b: httpx.Response(500, json={"detail": "boom"}))

    run_id = client.post("/api/v1/evaluation/runs", headers=auth("evaluator")).json()["data"]["id"]
    detail = client.get(f"/api/v1/evaluation/runs/{run_id}", headers=auth("evaluator")).json()[
        "data"
    ]
    assert detail["status"] == "COMPLETED"
    assert "500" in detail["results"][0]["error"]


def test_fr_ops_008_run_guards(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"], "doc": ["DOC_ADMIN"]})
    _use_rag(client, TestSession, lambda b: httpx.Response(200, json=_completion("a", [], [])))
    # 채택 후보 없음 → 422
    assert client.post("/api/v1/evaluation/runs", headers=auth("evaluator")).status_code == 422
    _accept(client, auth, _seed_down_answer(TestSession))
    # 실행 중(RUNNING) 이면 409
    with TestSession() as s:
        s.add(EvaluationRun(status="RUNNING", total=1, started_by="x"))
        s.commit()
    conflict = client.post("/api/v1/evaluation/runs", headers=auth("evaluator"))
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "EVALUATION_RUNNING"
    # 문서 관리자는 접근 불가
    assert client.get("/api/v1/evaluation/runs", headers=auth("doc")).status_code == 403


def test_fr_ops_008_stale_running_run_is_marked_failed(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30)
    with TestSession() as s:
        s.add(
            EvaluationRun(
                status="RUNNING", total=3, done=1, started_by="x", created_at=old, updated_at=old
            )
        )
        s.commit()
    run = client.get("/api/v1/evaluation/runs", headers=auth("evaluator")).json()["data"][0]
    assert run["status"] == "FAILED" and "중단됨" in run["error"]

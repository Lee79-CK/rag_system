"""chat_adapter 단위 테스트 — 답변 blocks 렌더, 피드백 토큰, delta coalescing, PostDto 매핑."""

from __future__ import annotations

from datetime import UTC, datetime

from chat_adapter import (
    PostRow,
    StreamEmitter,
    feedback_token,
    render_answer,
    to_post_dto,
    verify_feedback_token,
)
from pydantic import TypeAdapter
from rag_schemas import Citation, RagCompletion
from rag_schemas.webchat import Block, UserBrief


class SpyManager:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, str | None]] = []

    async def emit(self, event, data, namespace=None, room=None, **kw):
        self.events.append((event, data, room))


def _completion(**over) -> RagCompletion:
    base = {
        "message_id": "m1",
        "answer": "VPN 재접속 절차는 다음과 같습니다.",
        "citations": [
            Citation(
                document_id="d1",
                document_name="장애대응매뉴얼.pdf",
                page=3,
                section="VPN",
                excerpt="x" * 500,
                score=0.9,
                chunk_id="c1",
            )
        ],
    }
    base.update(over)
    return RagCompletion(**base)


def test_render_answer_mentions_and_citation_table():
    message, blocks = render_answer(_completion(), user_name="hong", mention=True)
    assert message.startswith("@hong VPN")
    table = blocks[0]
    assert table["type"] == "table" and table["block_id"] == "citations"
    assert table["rows"][0]["doc"] == "장애대응매뉴얼.pdf"
    assert table["rows"][0]["loc"] == "p.3 · VPN"
    assert len(table["rows"][0]["excerpt"]) == 200
    # chat-web BlockRenderer 계약(Block union)으로 검증 가능해야 한다.
    TypeAdapter(list[Block]).validate_python(blocks)


def test_render_answer_insufficient_evidence_context_block():
    message, blocks = render_answer(
        _completion(citations=[], insufficient_evidence=True), user_name="hong", mention=False
    )
    assert not message.startswith("@")
    assert [b["type"] for b in blocks] == ["context"]


def test_fb_feedback_token_binds_message_and_post():
    tok = feedback_token(b"key", "m1", "p1")
    assert verify_feedback_token(b"key", "m1", "p1", tok)
    assert not verify_feedback_token(b"key", "m1", "p2", tok)
    assert not verify_feedback_token(b"other", "m1", "p1", tok)
    assert not verify_feedback_token(b"", "m1", "p1", tok)


async def test_delta_stream_coalesces_and_sequences():
    spy = SpyManager()
    now = [0.0]
    stream = StreamEmitter(spy).open_stream(post_id="bp", channel_id="c1", root_id=None)
    stream._clock = lambda: now[0]  # 결정론적 시계
    stream._last = 0.0
    for tok in ["안", "녕", "하", "세요"]:
        await stream.push(tok)  # 64자/50ms 미만 → 버퍼링
    assert spy.events == []
    now[0] = 0.06
    await stream.push("!")  # 50ms 경과 → flush
    await stream.push("끝")
    await stream.flush()
    deltas = [e for e in spy.events if e[0] == "llm.stream.delta"]
    assert [d[1]["seq"] for d in deltas] == [1, 2]
    assert "".join(d[1]["delta"] for d in deltas) == "안녕하세요!끝" == stream.text
    assert all(room == "channel:c1" for _, _, room in deltas)


async def test_emitter_post_updated_and_end_target_channel_room():
    spy = SpyManager()
    em = StreamEmitter(spy)
    dto = to_post_dto(
        PostRow(
            id="bp",
            channel_id="c1",
            root_id="r1",
            type="bot",
            message="답",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            props={"streaming": False, "message_id": "m1"},
            user=UserBrief(id="bot", display_name="RAG Assistant", is_bot=True),
        )
    )
    await em.post_updated(dto)
    await em.end(post_id="bp", channel_id="c1", root_id="r1")
    assert [e[0] for e in spy.events] == ["post.updated", "llm.stream.end"]
    assert spy.events[0][1]["created_at"].startswith("2026-01-01T00:00:00")


def test_mapper_hides_internal_props():
    dto = to_post_dto(
        PostRow(
            id="p",
            channel_id="c",
            root_id=None,
            type="bot",
            message="x",
            created_at="2026-01-01T00:00:00Z",
            props={"message_id": "m-secret-link", "feedback_token": "t", "streaming": False},
        )
    )
    assert "message_id" not in dto.props
    assert dto.props["feedback_token"] == "t"

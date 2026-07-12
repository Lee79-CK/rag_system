"""libs/mattermost-adapter 단위 테스트 — 정규화/렌더링/서명."""

from __future__ import annotations

import hmac
from hashlib import sha256

from mattermost_adapter import (
    build_feedback_attachment,
    feedback_signature,
    normalize_outgoing_payload,
    render_answer,
    split_post,
)
from rag_schemas import Citation, RagCompletion


def test_normalize_form_payload_coerces_timestamp():
    p = normalize_outgoing_payload(
        {
            "token": "t",
            "team_id": "team-001",
            "channel_id": "c1",
            "channel_name": "n",
            "user_id": "u",
            "user_name": "un",
            "post_id": "p",
            "text": "질문",
            "timestamp": "1720000000",
        }
    )
    assert p.timestamp == 1720000000
    assert p.root_id == ""


def test_render_answer_with_mention_and_citations():
    completion = RagCompletion(
        message_id="m1",
        answer="장애 등급은 1~4등급입니다. [1]",
        citations=[
            Citation(
                document_id="d1",
                document_name="장애대응매뉴얼",
                page=12,
                section="3.2",
                excerpt="등급별 절차",
                score=0.9,
                chunk_id="v1-00012",
            )
        ],
    )
    text = render_answer("hong", completion, mention=True)
    assert text.startswith("@hong **답변**")
    assert "**근거 문서**" in text
    assert "`장애대응매뉴얼` p.12" in text


def test_render_answer_insufficient_evidence_note():
    completion = RagCompletion(message_id="m1", answer="근거 없음", insufficient_evidence=True)
    text = render_answer("hong", completion, mention=False)
    assert "근거가 충분하지 않습니다" in text


def test_feedback_signature_matches_hmac():
    key = b"secret-key"
    sig = feedback_signature(key, "m1", "UP")
    expected = hmac.new(key, b"m1:UP", sha256).hexdigest()
    assert sig == expected


def test_build_feedback_attachment_structure():
    att = build_feedback_attachment("m1", "j1", b"k", "http://bridge/actions")
    actions = att["actions"]
    assert {a["id"] for a in actions} == {"fb_up", "fb_down"}
    up = next(a for a in actions if a["id"] == "fb_up")
    assert up["integration"]["url"] == "http://bridge/actions"
    assert up["integration"]["context"]["value"] == "UP"
    assert up["integration"]["context"]["action"] == "feedback"


def test_split_post_short_text_single_part():
    assert split_post("hello", 100) == ["hello"]


def test_split_post_splits_on_line_boundaries():
    text = "\n".join(f"line-{i}" for i in range(100))
    parts = split_post(text, 50)
    assert len(parts) > 1
    assert "\n".join(parts).replace("\n", "") == text.replace("\n", "")

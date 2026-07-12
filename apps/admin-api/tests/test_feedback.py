"""피드백 집계 테스트 — §7.5 read-only 엔드포인트, 만족률 계산."""

from __future__ import annotations

from admin.db.models import ChannelConversation, Message, MessageFeedbackRow


def _seed_feedback(TestSession, up: int, down: int, channel_id: str = "c1") -> str:
    with TestSession() as s:
        conv = ChannelConversation(
            scope_key=f"t1:{channel_id}", team_id="t1", channel_id=channel_id, mode="CHANNEL"
        )
        s.add(conv)
        s.flush()
        msg = Message(conversation_id=conv.id, role="assistant", content="답변입니다.")
        s.add(msg)
        s.flush()
        for i in range(up):
            s.add(
                MessageFeedbackRow(
                    message_id=msg.id,
                    mattermost_user_id=f"up-{i}",
                    value="UP",
                    channel_id=channel_id,
                )
            )
        for i in range(down):
            s.add(
                MessageFeedbackRow(
                    message_id=msg.id,
                    mattermost_user_id=f"down-{i}",
                    value="DOWN",
                    channel_id=channel_id,
                )
            )
        s.commit()
        return str(msg.id)


def test_feedback_summary_ratio(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    _seed_feedback(TestSession, up=7, down=3)

    resp = client.get("/api/v1/feedback/summary", headers=auth("evaluator"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["up"] == 7
    assert data["down"] == 3
    assert data["total"] == 10
    # 만족률 = UP / (UP + DOWN)
    assert data["satisfaction_ratio"] == 0.7


def test_feedback_by_channel(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    _seed_feedback(TestSession, up=2, down=2, channel_id="cA")

    resp = client.get("/api/v1/feedback/by-channel", headers=auth("evaluator"))
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    entry = next(r for r in rows if r["channel_id"] == "cA")
    assert entry["up"] == 2
    assert entry["down"] == 2
    assert entry["satisfaction_ratio"] == 0.5


def test_feedback_messages_down_with_citations(client, TestSession, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    msg_id = _seed_feedback(TestSession, up=0, down=1)

    resp = client.get(
        "/api/v1/feedback/messages", params={"value": "DOWN"}, headers=auth("sysadmin")
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["message_id"] == msg_id
    assert items[0]["value"] == "DOWN"
    assert "citations" in items[0]


def test_message_feedback_detail(client, TestSession, seed, auth):
    seed({"evaluator": ["QUALITY_EVALUATOR"]})
    msg_id = _seed_feedback(TestSession, up=1, down=1)

    resp = client.get(f"/api/v1/messages/{msg_id}/feedback", headers=auth("evaluator"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["up"] == 1
    assert data["down"] == 1
    assert data["satisfaction_ratio"] == 0.5

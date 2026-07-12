"""libs/observability 단위 테스트 — secret 마스킹 및 로깅 설정."""

from __future__ import annotations

from rag_observability import configure_logging, get_logger, mask_secrets


def test_mask_secrets_masks_sensitive_keys():
    masked = mask_secrets(
        {
            "token": "abc123",
            "incoming_webhook_url": "https://mm/hooks/x",
            "feedback_signing_key": "deadbeef",
            "channel_id": "channel-001",
            "nested": {"secret_ref": "name-ok", "authorization": "Bearer y"},
        }
    )
    assert masked["token"] == "***"
    assert masked["incoming_webhook_url"] == "***"
    assert masked["feedback_signing_key"] == "***"
    # 비민감 필드는 유지
    assert masked["channel_id"] == "channel-001"
    # secret_ref 도 'secret' 힌트에 걸려 마스킹됨 (보수적)
    assert masked["nested"]["secret_ref"] == "***"
    assert masked["nested"]["authorization"] == "***"


def test_mask_secrets_handles_lists():
    masked = mask_secrets([{"token": "x"}, {"channel_id": "c"}])
    assert masked[0]["token"] == "***"
    assert masked[1]["channel_id"] == "c"


def test_configure_logging_and_get_logger():
    configure_logging("test-service", level="DEBUG")
    log = get_logger("t")
    # 예외 없이 로그 호출이 동작해야 한다 (secret은 마스킹됨).
    log.info("event", token="should-be-masked", channel_id="c1")

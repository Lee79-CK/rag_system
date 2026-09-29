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


def test_mask_secrets_value_patterns_in_plain_strings():
    """키 이름이 무해해도(event/exception) 값 안의 DSN 비밀번호·webhook 경로·Bearer 는 가려진다."""
    from rag_observability.masking import _structlog_processor

    event = {
        "event": "connect failed: postgresql+psycopg://rag:pw-1234@postgresql.rag-data:5432/rag",
        "exception": [
            {
                "exc_value": "POST https://mm.internal/hooks/abcDEF123 -> 404",
                "frames": [{"locals": {"auth": "Bearer eyJhbGciOi.xyz"}}],
            }
        ],
        "channel_id": "channel-001",
    }
    masked = _structlog_processor(None, "error", event)
    dumped = str(masked)
    assert "pw-1234" not in dumped
    assert "abcDEF123" not in dumped
    assert "eyJhbGciOi" not in dumped
    assert "rag:***@postgresql.rag-data" in masked["event"]
    assert masked["channel_id"] == "channel-001"


def test_processor_order_masks_after_dict_tracebacks(capsys):
    """dict_tracebacks 뒤에 마스킹이 와야 예외 본문 안의 secret 이 걸러진다."""
    configure_logging("test-service", level="DEBUG")
    log = get_logger("t")
    try:
        raise RuntimeError("dsn=redis://:redis-secret-pw@redis.rag-data:6379/0")
    except RuntimeError:
        log.exception("boom")
    out = capsys.readouterr()
    assert "redis-secret-pw" not in out.out + out.err


def test_mask_web_chat_credentials():
    """Web Chat 자격 증명(prehash/pepper/cookie 키, bare JWT 값) 마스킹 (v2.0)."""
    from rag_common import jwt
    from rag_observability import mask_secrets

    tok = jwt.encode({"sub": "u1"}, b"k" * 32, ttl_seconds=60)
    out = mask_secrets(
        {"prehash": "abc", "password_pepper": "p", "set_cookie": "rag_rt=xyz", "msg": f"auth {tok}"}
    )
    assert out["prehash"] == out["password_pepper"] == out["set_cookie"] == "***"
    assert tok not in out["msg"] and tok.rsplit(".", 1)[0] in out["msg"]

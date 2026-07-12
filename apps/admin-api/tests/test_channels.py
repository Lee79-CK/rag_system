"""Channel/Binding + secret 노출 금지 테스트 — FR-OPS-010, NFR-SEC-006."""

from __future__ import annotations

# 실제 Webhook URL을 흉내낸 sentinel — 어떤 GET 응답에도 등장해서는 안 된다.
SECRET_URL_SENTINEL = "https://mattermost.internal.example/hooks/xxxxSECRETxxxx"


def _create_channel_with_binding(client, auth) -> tuple[str, str]:
    ch = client.post(
        "/api/v1/mattermost/channels",
        json={"team_id": "t1", "channel_id": "c1", "channel_name": "general"},
        headers=auth("sysadmin"),
    )
    assert ch.status_code == 201, ch.text
    channel_id = ch.json()["data"]["id"]

    binding = client.post(
        f"/api/v1/mattermost/channels/{channel_id}/bindings",
        json={"secret_ref": "mm-incoming-webhook-secret", "enabled": True},
        headers=auth("sysadmin"),
    )
    assert binding.status_code == 201, binding.text
    return channel_id, binding.json()["data"]["id"]


def test_secret_value_never_in_get_responses(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id, binding_id = _create_channel_with_binding(client, auth)

    # secret 등록: 값(URL)은 절대 저장하지 않으며 응답에도 없어야 한다.
    sec = client.post(
        f"/api/v1/mattermost/channels/{channel_id}/secret",
        json={"secret_ref": "mm-incoming-webhook-secret"},
        headers=auth("sysadmin"),
    )
    assert sec.status_code == 200, sec.text
    sec_body = sec.json()
    assert sec_body["data"]["secret_ref"] == "mm-incoming-webhook-secret"
    assert sec_body["data"]["secret_updated_at"] is not None
    # 등록 응답에도 URL/값이 없어야 한다.
    assert SECRET_URL_SENTINEL not in sec.text
    assert "webhook_url" not in sec.text.lower()

    # GET channel (bindings 포함) — secret_ref만 존재, 값 부재.
    got = client.get(f"/api/v1/mattermost/channels/{channel_id}", headers=auth("sysadmin"))
    assert got.status_code == 200, got.text
    text = got.text
    assert "secret_ref" in text
    assert SECRET_URL_SENTINEL not in text
    assert "webhook_url" not in text.lower()
    assert "secret_value" not in text.lower()

    binding_view = got.json()["data"]["bindings"][0]
    # 어떤 필드도 실제 URL을 담지 않는다.
    assert binding_view["secret_ref"] == "mm-incoming-webhook-secret"
    assert "http" not in str(binding_view).lower()


def test_binding_enable_disable(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    _, binding_id = _create_channel_with_binding(client, auth)

    dis = client.post(f"/api/v1/mattermost/bindings/{binding_id}/disable", headers=auth("sysadmin"))
    assert dis.status_code == 200
    assert dis.json()["data"]["enabled"] is False

    en = client.post(f"/api/v1/mattermost/bindings/{binding_id}/enable", headers=auth("sysadmin"))
    assert en.status_code == 200
    assert en.json()["data"]["enabled"] is True


def test_connection_test_stub(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id, _ = _create_channel_with_binding(client, auth)
    resp = client.post(f"/api/v1/mattermost/channels/{channel_id}/test", headers=auth("sysadmin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["ok"] is True
    # 연결 테스트 응답에도 URL 노출 금지.
    assert SECRET_URL_SENTINEL not in resp.text

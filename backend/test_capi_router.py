"""End-to-end tests for POST /api/capi/lead.

Covers the wiring (route registered, auth-exempt from the dashboard session) and the three
status codes ChatPlace reacts to, since a non-2xx is what sets the webhook_failed tag.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend import capi_bridge
from backend.capi_bridge import remember_identity, reset_identity_cache

SECRET = "cpwh_test_secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATPLACE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("META_PIXEL_ID", "1255735776468620")
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_668405878867091")
    # Keep both the identity bridge and the funnel log inside tmp_path.
    monkeypatch.setattr(capi_bridge, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr("backend.funnel_events.STORAGE_DIR", tmp_path)
    monkeypatch.setattr("backend.routers.capi.save_funnel_event", lambda payload: payload)
    reset_identity_cache()
    yield TestClient(app)
    reset_identity_cache()


def post(client, body, *, secret=SECRET):
    headers = {"x-chatplace-secret": secret} if secret else {}
    return client.post("/api/capi/lead", json=body, headers=headers)


def test_rejects_a_wrong_secret(client):
    response = post(client, {"phone": "+998901234567"}, secret="nope")
    assert response.status_code == 401


def test_dry_run_builds_a_matchable_event_when_the_token_is_known(client, tmp_path):
    remember_identity(
        {"visitor_id": "v_abc123", "fbp": "fb.1.1700.111", "fbc": "fb.1.1700.CLICK", "user_agent": "UA/1.0"},
        storage_dir=tmp_path,
    )
    response = post(
        client,
        {
            "name": "Nozimaxon",
            "phone": "+998901234567",
            "telegram": "nozima",
            "start_payload": "/start v_abc123",
            "dry_run": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "v_abc123"
    assert body["matched"] is True
    assert body["sent"] is False
    assert {"ph", "fn", "external_id", "fbp", "fbc"} <= set(body["matchKeys"])


def test_reports_unmatched_when_the_token_never_reached_the_bot(client):
    # The failure mode to watch for: ChatPlace could not read the start payload. Still a 200,
    # because retrying will not fix it — but matched:false makes it visible.
    response = post(client, {"phone": "+998901234567", "start_payload": "/start", "dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["token"] is None
    assert body["matched"] is False
    assert "fbp" not in body["matchKeys"]


def test_sends_to_meta_and_returns_the_trace_id(client, tmp_path, monkeypatch):
    sent = {}

    async def fake_send(config, events, **kwargs):
        sent["events"] = events
        sent["kwargs"] = kwargs
        return {"events_received": 1, "fbtrace_id": "AbC123"}

    monkeypatch.setattr("backend.routers.capi.send_capi_events", fake_send)
    remember_identity({"visitor_id": "v_abc123", "fbp": "fb.1.1.1"}, storage_dir=tmp_path)

    response = post(client, {"phone": "+998901234567", "start_payload": "/start v_abc123"})
    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is True and body["matched"] is True
    assert body["eventsReceived"] == 1 and body["fbtraceId"] == "AbC123"
    assert sent["events"][0]["event_name"] == "CRMLead"


def test_meta_failure_returns_502_so_chatplace_tags_it(client, monkeypatch):
    from backend.meta_client import MetaApiError

    async def boom(config, events, **kwargs):
        raise MetaApiError("Invalid parameter")

    monkeypatch.setattr("backend.routers.capi.send_capi_events", boom)
    response = post(client, {"phone": "+998901234567", "start_payload": "/start v_abc123"})
    # 502, not 200 — a silent CAPI failure is the exact thing that hid the July problem.
    assert response.status_code == 502
    assert "Invalid parameter" in response.json()["detail"]


def test_test_event_code_is_forwarded_for_events_manager_verification(client, monkeypatch):
    captured = {}

    async def fake_send(config, events, **kwargs):
        captured.update(kwargs)
        return {"events_received": 1}

    monkeypatch.setattr("backend.routers.capi.send_capi_events", fake_send)
    post(client, {"phone": "+998901234567", "start_payload": "/start v_abc123", "test_event_code": "TEST12345"})
    assert captured["test_event_code"] == "TEST12345"


def test_landing_beacon_stores_the_identity(client, tmp_path):
    # The landing page posts once; that same POST must feed the bridge.
    response = client.post(
        "/api/funnel/events",
        json={
            "event": {
                "event_name": "landing_cta",
                "visitor_id": "v_landing99",
                "fbp": "fb.1.1700.222",
                "fbc": "fb.1.1700.CLICK",
                "user_agent": "UA/2.0",
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["identityStored"] is True
    assert capi_bridge.lookup_identity("v_landing99", storage_dir=tmp_path)["fbp"] == "fb.1.1700.222"

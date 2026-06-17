"""Telegram KPI digest scope picker (kpi: callbacks): pin a campaign, reset to
account-wide, and RBAC (viewers may browse/show but not change the scope)."""

import json

from fastapi.testclient import TestClient

import backend.kpi_digest_campaign_store as kpi_store
import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
from backend.app import app
from backend.test_telegram_command_api import bind_tmp_command_store


def _mock_account(monkeypatch, campaigns):
    monkeypatch.setattr(
        telegram_router,
        "_live_account_sync",
        lambda: {"campaigns": campaigns, "adsets": [], "ads": [], "account_id": "act_1", "source": "test"},
    )


def _mock_store(monkeypatch):
    """In-memory stand-in for the global KPI campaign store."""
    state: dict = {}

    def _set(campaign_id, campaign_name="", *, selected_by=None, **kw):
        state["sel"] = {"campaignId": str(campaign_id), "campaignName": campaign_name, "selectedBy": selected_by}
        return state["sel"]

    monkeypatch.setattr(kpi_store, "load_kpi_digest_campaign", lambda **kw: state.get("sel"))
    monkeypatch.setattr(kpi_store, "set_kpi_digest_campaign", _set)
    monkeypatch.setattr(kpi_store, "clear_kpi_digest_campaign", lambda **kw: state.pop("sel", None))
    return state


def _mock_edits(monkeypatch):
    edits = []
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_outbound,
        "edit_message_text",
        lambda chat_id, message_id, text, **k: edits.append(text) or {"ok": True},
    )
    return edits


def _callback(data, *, user_id=2002, username="akmal"):
    return {
        "callback_query": {
            "id": "cb",
            "from": {"id": user_id, "username": username},
            "message": {"chat": {"id": 1001}, "message_id": 7},
            "data": data,
        }
    }


def test_kpi_pick_sets_campaign_and_renders_full_name(monkeypatch, tmp_path):
    _, _sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    _mock_account(monkeypatch, [{"id": "c1", "name": "DA - SHAHLOAI - VSL - 16.06.2026"}])
    state = _mock_store(monkeypatch)
    edits = _mock_edits(monkeypatch)

    response = TestClient(app).post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json=_callback("kpi:c:c1"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kpi"] == "set" and body["campaign"] == "c1"
    assert state["sel"]["campaignId"] == "c1"
    # The panel is re-rendered naming the watched campaign (full name visible).
    assert edits and "Now watching" in edits[-1]
    assert "16.06.2026" in edits[-1]


def test_kpi_reset_clears_to_account_wide(monkeypatch, tmp_path):
    _, _sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    _mock_account(monkeypatch, [{"id": "c1", "name": "Camp One"}])
    state = _mock_store(monkeypatch)
    state["sel"] = {"campaignId": "c1", "campaignName": "Camp One"}
    edits = _mock_edits(monkeypatch)

    response = TestClient(app).post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json=_callback("kpi:reset"),
    )

    assert response.status_code == 200 and response.json()["kpi"] == "reset"
    assert "sel" not in state
    assert edits and "account-wide" in edits[-1]


def test_kpi_pick_denied_for_viewer(monkeypatch, tmp_path):
    # Seed an owner + a viewer; the viewer must not be able to change the digest scope.
    path = tmp_path / "members.json"
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(path))
    path.write_text(
        json.dumps(
            [
                {"userId": "1001", "username": None, "role": "owner", "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"},
                {"userId": "5005", "username": "viewer1", "role": "viewer", "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    sent = []
    monkeypatch.setattr(telegram_outbound, "send_telegram_message_sync", lambda text, **kwargs: sent.append(text) or {"ok": True})
    _mock_account(monkeypatch, [{"id": "c1", "name": "Camp One"}])
    state = _mock_store(monkeypatch)
    _mock_edits(monkeypatch)

    response = TestClient(app).post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json=_callback("kpi:c:c1", user_id=5005, username="viewer1"),
    )

    assert response.status_code == 200
    assert response.json().get("denied") == "viewer_action"
    assert "sel" not in state  # nothing pinned

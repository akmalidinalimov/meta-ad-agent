import asyncio

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app
from backend.approval_store import create_approval_request, list_approval_requests
from backend.meta_execution import build_campaign_creation_approval
from backend.telegram_outbound import build_approval_notification, send_telegram_message


def test_build_approval_notification_contains_approve_button():
    approval = build_campaign_creation_approval(
        {
            "name": "Outbound notification test",
            "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
            "rules": {"maxDailyBudgetUsd": 100},
        },
        account_id="act_123",
    )

    notification = build_approval_notification(approval)

    assert "Outbound notification test - DRAFT" in notification["text"]
    assert notification["reply_markup"]["inline_keyboard"][0][0]["text"] == "Approve"
    assert notification["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"approve:{approval['id']}"
    assert notification["reply_markup"]["inline_keyboard"][0][1]["text"] == "Reject"
    assert notification["reply_markup"]["inline_keyboard"][0][1]["callback_data"] == f"reject:{approval['id']}"
    assert notification["reply_markup"]["inline_keyboard"][1][0]["text"] == "Needs changes"
    assert notification["reply_markup"]["inline_keyboard"][1][0]["callback_data"] == f"changes:{approval['id']}"


def test_send_telegram_message_reports_missing_config(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)

    result = asyncio.run(send_telegram_message("Hello"))

    assert result["ok"] is False
    assert result["skipped"] is True
    assert "not configured" in result["error"].lower()


def test_prepare_campaign_execution_sends_telegram_notification(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    sent = []
    monkeypatch.setattr(app_module, "create_approval_request", lambda request: create_approval_request(request, storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "send_approval_notification", lambda approval: sent.append(approval) or {"ok": True})
    client = TestClient(app)

    response = client.post(
        "/api/execution/prepare-campaign",
        json={
            "playbook": {
                "id": "pb_notify",
                "name": "Notify launch",
                "segments": [{"id": "business", "name": "Business", "startingBudgetUsd": 100}],
                "rules": {"maxDailyBudgetUsd": 200},
            }
        },
    )

    assert response.status_code == 200
    assert sent[0]["id"] == response.json()["approval"]["id"]


def test_telegram_test_message_endpoint_uses_sender(monkeypatch):
    sent = []
    monkeypatch.setattr(app_module, "send_telegram_message_sync", lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True})
    client = TestClient(app)

    response = client.post("/api/telegram/test-message", json={"message": "Agent approval test"})

    assert response.status_code == 200
    assert sent == [("Agent approval test", {})]

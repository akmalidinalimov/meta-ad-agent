from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task
from backend.app import app
from backend.approval_store import (
    approve_request,
    create_approval_request,
    list_approval_requests,
    reject_request,
    request_changes,
)
from backend.meta_execution import build_campaign_creation_approval


def bind_tmp_command_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    sent = []
    monkeypatch.setattr(app_module, "create_agent_task", lambda task: create_agent_task(task, storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(
        app_module,
        "update_agent_task",
        lambda task_id, patch: update_agent_task(task_id, patch, storage_dir=storage_dir),
    )
    monkeypatch.setattr(app_module, "create_approval_request", lambda request: create_approval_request(request, storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(
        app_module,
        "approve_request",
        lambda approval_id, *, approved_by: approve_request(approval_id, approved_by=approved_by, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        app_module,
        "reject_request",
        lambda approval_id, *, rejected_by, reason: reject_request(
            approval_id,
            rejected_by=rejected_by,
            reason=reason,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "request_changes",
        lambda approval_id, *, requested_by, note: request_changes(
            approval_id,
            requested_by=requested_by,
            note=note,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "send_telegram_message_sync",
        lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True, "mock": True},
    )
    return storage_dir, sent


def test_telegram_command_creates_agent_task(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "Create a campaign with 3 VSLs: income, business automation, creators. Use $100 each.",
            }
        },
    )

    payload = response.json()
    tasks = client.get("/api/tasks").json()["tasks"]

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["task"]["source"] == "telegram"
    assert payload["telegram"]["chatId"] == "1001"
    assert tasks[0]["requestedAction"].startswith("Create a campaign")
    assert tasks[0]["activeAgent"] == "orchestrator"
    assert sent[0][1]["chat_id"] == "1001"
    assert "approval-ready campaign plan" in sent[0][0]


def test_telegram_command_rejects_invalid_secret(monkeypatch, tmp_path):
    bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "wrong"},
        json={"message": {"text": "Create campaign"}},
    )

    assert response.status_code == 401


def test_telegram_callback_can_approve_existing_approval(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    request = build_campaign_creation_approval(
        {
            "name": "Telegram approval test",
            "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
            "rules": {"maxDailyBudgetUsd": 100},
        },
        account_id="act_123",
    )
    saved = create_approval_request(request, storage_dir=tmp_path / "storage")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "callback_query": {
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}},
                "data": f"approve:{saved['id']}",
            }
        },
    )

    approvals = client.get("/api/approvals").json()["approvals"]

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "approved"
    assert approvals[0]["approvedBy"] == "telegram:akmal"
    assert sent[0][1]["chat_id"] == "1001"
    assert "Approval recorded" in sent[0][0]


def test_telegram_callback_can_reject_existing_approval(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    saved = create_approval_request(
        build_campaign_creation_approval(
            {
                "name": "Telegram reject test",
                "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
                "rules": {"maxDailyBudgetUsd": 100},
            },
            account_id="act_123",
        ),
        storage_dir=tmp_path / "storage",
    )
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "callback_query": {
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}},
                "data": f"reject:{saved['id']}",
            }
        },
    )

    approvals = client.get("/api/approvals").json()["approvals"]

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "rejected"
    assert approvals[0]["rejectedBy"] == "telegram:akmal"
    assert "rejected" in sent[0][0].lower()


def test_telegram_callback_can_mark_approval_needs_changes(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    saved = create_approval_request(
        build_campaign_creation_approval(
            {
                "name": "Telegram changes test",
                "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
                "rules": {"maxDailyBudgetUsd": 100},
            },
            account_id="act_123",
        ),
        storage_dir=tmp_path / "storage",
    )
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "callback_query": {
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}},
                "data": f"changes:{saved['id']}",
            }
        },
    )

    approvals = client.get("/api/approvals").json()["approvals"]

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "needs_changes"
    assert approvals[0]["changesRequestedBy"] == "telegram:akmal"
    assert "needs changes" in sent[0][0].lower()

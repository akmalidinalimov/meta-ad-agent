from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task
from backend.app import app
from backend.approval_store import approve_request, create_approval_request, list_approval_requests
from backend.meta_execution import build_campaign_creation_approval


def bind_tmp_command_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
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
    return storage_dir


def test_telegram_command_creates_agent_task(monkeypatch, tmp_path):
    bind_tmp_command_store(monkeypatch, tmp_path)
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
    bind_tmp_command_store(monkeypatch, tmp_path)
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

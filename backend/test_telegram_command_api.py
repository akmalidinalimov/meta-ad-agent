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
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "1001")
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
    assert "Agent: orchestrator" in sent[0][0]
    assert "Quality:" in sent[0][0]
    assert "Involved agents:" in sent[0][0]
    assert "Next:" in sent[0][0]


def test_telegram_natural_language_meta_action_creates_approval(monkeypatch, tmp_path):
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
                "text": "Rename campaign 120123 to Business Automation VSL - Tashkent",
            }
        },
    )

    payload = response.json()
    approvals = client.get("/api/approvals").json()["approvals"]

    assert response.status_code == 200
    assert payload["task"]["status"] == "needs_approval"
    assert payload["task"]["activeAgent"] == "execution"
    assert approvals[0]["actionType"] == "rename_meta_object"
    assert approvals[0]["target"]["id"] == "120123"
    assert "approval-gated Meta action" in sent[-1][0]


def test_telegram_status_command_replies_without_creating_task(monkeypatch, tmp_path):
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
                "text": "/status",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["shortcut"] == "status"
    assert client.get("/api/tasks").json()["tasks"] == []
    assert "Agent status" in sent[0][0]


def test_telegram_attention_question_replies_with_monitoring_context(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    monkeypatch.setattr(app_module, "list_monitoring_alerts", lambda: [{"title": "Lead rate dropped", "severity": "medium"}])
    monkeypatch.setattr(app_module, "list_monitoring_runs", lambda: [{"status": "completed", "finishedAt": "2026-06-01T10:00:00Z", "alertsCreated": 1}])
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "what needs attention now?",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["shortcut"] == "attention"
    assert "What needs attention now" in sent[0][0]
    assert "Lead rate dropped" in sent[0][0]
    assert client.get("/api/tasks").json()["tasks"] == []


def test_telegram_tasks_and_approvals_commands_show_queue(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    create_agent_task(
        {"source": "dashboard", "command": "Prepare launch", "status": "needs_approval", "approvalId": "approval_123"},
        storage_dir=tmp_path / "storage",
    )
    create_approval_request(
        build_campaign_creation_approval(
            {
                "name": "Queue approval",
                "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
                "rules": {"maxDailyBudgetUsd": 100},
            },
            account_id="act_123",
        ),
        storage_dir=tmp_path / "storage",
    )
    client = TestClient(app)

    tasks_response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={"message": {"chat": {"id": 1001}, "from": {"username": "akmal"}, "text": "/tasks"}},
    )
    approvals_response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={"message": {"chat": {"id": 1001}, "from": {"username": "akmal"}, "text": "/approvals"}},
    )

    assert tasks_response.json()["shortcut"] == "tasks"
    assert approvals_response.json()["shortcut"] == "approvals"
    assert "Prepare launch" in sent[0][0]
    assert "Queue approval" in sent[1][0]


def test_telegram_agents_and_help_commands_reply(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    client = TestClient(app)

    agents_response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={"message": {"chat": {"id": 1001}, "from": {"username": "akmal"}, "text": "/agents"}},
    )
    help_response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={"message": {"chat": {"id": 1001}, "from": {"username": "akmal"}, "text": "/help"}},
    )

    assert agents_response.json()["shortcut"] == "agents"
    assert help_response.json()["shortcut"] == "help"
    assert "Orchestrator Agent" in sent[0][0]
    assert "/approvals" in sent[1][0]


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


def test_telegram_command_rejects_unallowed_chat(monkeypatch, tmp_path):
    bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "1001")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 9999},
                "from": {"id": 9999, "username": "stranger"},
                "text": "/status",
            }
        },
    )

    assert response.status_code == 403


def test_telegram_command_allows_configured_user_id(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "2002,3003")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 9999},
                "from": {"id": 2002, "username": "akmal"},
                "text": "/status",
            }
        },
    )

    assert response.status_code == 200
    assert sent[0][1]["chat_id"] == "9999"


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

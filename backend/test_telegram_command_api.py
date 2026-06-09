from fastapi.testclient import TestClient

import backend.agent_task_store as agent_task_store
import backend.approval_store as approval_store
import backend.monitoring_runner as monitoring_runner
import backend.monitoring_scheduler as monitoring_scheduler
import backend.telegram_outbound as telegram_outbound
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task
from backend.app import app
import backend.task_service as task_service_mod
import backend.routers.approvals as approvals_router_mod
import backend.routers.tasks as tasks_router_mod
import backend.telegram_service as telegram_service_mod
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
    monkeypatch.setattr(agent_task_store, "create_agent_task", lambda task: create_agent_task(task, storage_dir=storage_dir))
    monkeypatch.setattr(tasks_router_mod, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(telegram_service_mod, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(task_service_mod, "update_agent_task", lambda task_id, patch: update_agent_task(task_id, patch, storage_dir=storage_dir))
    monkeypatch.setattr(approval_store, "create_approval_request", lambda request: create_approval_request(request, storage_dir=storage_dir))
    monkeypatch.setattr(approvals_router_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(telegram_service_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(
        approval_store,
        "approve_request",
        lambda approval_id, *, approved_by: approve_request(approval_id, approved_by=approved_by, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        approval_store,
        "reject_request",
        lambda approval_id, *, rejected_by, reason: reject_request(
            approval_id,
            rejected_by=rejected_by,
            reason=reason,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        approval_store,
        "request_changes",
        lambda approval_id, *, requested_by, note: request_changes(
            approval_id,
            requested_by=requested_by,
            note=note,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        telegram_outbound,
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
    assert sent[0][1]["parse_mode"] == "HTML"
    body = sent[0][0]
    # Humanized HTML structure: emoji header, bold metadata, delimited sections.
    assert "<b>🤖 Orchestrator</b>" in body
    assert "approval-ready campaign plan" in body
    assert "Agent: <b>orchestrator</b>" in body
    assert "Quality:" in body
    assert "Involved agents:" in body
    assert "<b>Next:</b>" in body
    assert "🔒 Safety:" in body


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
    assert "<b>📈 Agent status</b>" in sent[0][0]
    assert sent[0][1]["parse_mode"] == "HTML"


def test_telegram_attention_question_replies_with_monitoring_context(monkeypatch, tmp_path):
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    monkeypatch.setattr(monitoring_runner, "list_monitoring_alerts", lambda: [{"title": "Lead rate dropped", "severity": "medium"}])
    monkeypatch.setattr(monitoring_scheduler, "list_monitoring_runs", lambda: [{"status": "completed", "finishedAt": "2026-06-01T10:00:00Z", "alertsCreated": 1}])
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
    assert "<b>🚨 What needs attention now</b>" in sent[0][0]
    assert "Lead rate dropped" in sent[0][0]
    assert sent[0][1]["parse_mode"] == "HTML"
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
                # Special chars exercise the HTML-escape path in telegram_approvals_text.
                "name": "Queue <approval> & more",
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
    assert "<b>🗒️ Latest tasks</b>" in sent[0][0]
    assert sent[0][1]["parse_mode"] == "HTML"
    assert "Prepare launch" in sent[0][0]
    assert "<b>📝 Latest approvals</b>" in sent[1][0]
    assert sent[1][1]["parse_mode"] == "HTML"
    # Dynamic campaign name with special chars must be HTML-escaped (no raw < or &).
    assert "Queue &lt;approval&gt; &amp; more" in sent[1][0]
    assert "Queue <approval> & more" not in sent[1][0]


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
    assert "<b>🤖 Available agents</b>" in sent[0][0]
    assert sent[0][1]["parse_mode"] == "HTML"
    assert "Orchestrator Agent" in sent[0][0]
    assert "<b>📖 Meta Agent commands</b>" in sent[1][0]
    assert sent[1][1]["parse_mode"] == "HTML"
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
    assert "Approved" in sent[0][0]


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


def test_telegram_native_secret_token_header_is_accepted(monkeypatch, tmp_path):
    """Telegram's setWebhook secret_token arrives as X-Telegram-Bot-Api-Secret-Token,
    so the bot can post updates to /api/telegram/command directly (no relay)."""
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    saved = create_approval_request(
        build_campaign_creation_approval(
            {
                "name": "Telegram native secret test",
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
        headers={"x-telegram-bot-api-secret-token": "secret"},
        json={
            "callback_query": {
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}},
                "data": f"approve:{saved['id']}",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "approved"


def test_telegram_wrong_native_secret_token_is_rejected(monkeypatch, tmp_path):
    bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    client = TestClient(app)

    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-bot-api-secret-token": "wrong"},
        json={"callback_query": {"data": "approve:whatever"}},
    )

    assert response.status_code == 401


def test_telegram_autonomous_build_auto_creates_paused(monkeypatch, tmp_path):
    """An autonomous build over Telegram auto-creates the PAUSED campaign immediately
    (no separate approval tap) and confirms what was created."""
    import backend.routers.telegram as telegram_router
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    # Isolate pending state (the router imports these names inside the handler).
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: None)
    monkeypatch.setattr(pending_store, "set_pending", lambda *a, **k: {})
    monkeypatch.setattr(pending_store, "clear_pending", lambda *a, **k: None)

    plan = {
        "activeAgent": "orchestrator",
        "answer": "I built a best-guess paused campaign on my own.",
        "autonomous": True,
        "generatedApprovalRequest": {
            "id": "autonomous_tg",
            "status": "needs_review",
            "guardrailResult": "pass",
            "after": {"campaign": {"name": "Best Guess - DRAFT"}, "adsets": [{"name": "AI - DRAFT", "daily_budget": 10000}]},
            "createdAt": "now",
        },
    }
    monkeypatch.setattr(
        telegram_router,
        "create_orchestrated_agent_task",
        lambda request: {"ok": True, "task": {"id": "task_1", "plan": plan}},
    )

    exec_calls = []
    monkeypatch.setattr(
        telegram_router,
        "auto_execute_paused",
        lambda approval_id: exec_calls.append(approval_id)
        or {
            "ok": True,
            "created": [
                {"level": "campaign", "id": "cmp_live", "name": "Best Guess - DRAFT"},
                {"level": "adset", "id": "as_live", "name": "AI - DRAFT"},
            ],
            "blocked": None,
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "just create a test on your own, you decide",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["autonomousCreated"] is True
    assert exec_calls == ["autonomous_tg"]
    body = sent[-1][0]
    assert "Created in Meta as <b>PAUSED</b>" in body
    assert "Best Guess - DRAFT" in body
    assert "1 campaign" in body
    assert "1 ad set" in body


def test_telegram_followup_refines_in_flight_draft(monkeypatch, tmp_path):
    """A non-question follow-up ("$150/day in Tashkent") refines the operator's in-flight
    autonomous draft (via the shared chat brain) instead of starting a fresh task."""
    import backend.routers.telegram as telegram_router
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    # The operator has a pending draft -> the action path must delegate to the chat brain.
    monkeypatch.setattr(
        pending_store, "get_pending", lambda op_key, **kw: {"approvalId": "autonomous_tg", "budget": 100.0}
    )

    conv_calls = []
    monkeypatch.setattr(
        telegram_router,
        "answer_agent_question_sync",
        lambda message, **kwargs: conv_calls.append((message, kwargs))
        or {"answer": "I refined your draft.", "sources": ["pending_context_store"]},
    )
    # If a fresh task were created instead, this would fire — assert it does NOT.
    monkeypatch.setattr(
        telegram_router,
        "create_orchestrated_agent_task",
        lambda request: (_ for _ in ()).throw(AssertionError("should not create a new task on refinement")),
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "make it $150/day in Tashkent",
            }
        },
    )

    assert response.status_code == 200
    # Delegated to the chat brain with the Telegram operator key so the same draft refines.
    assert conv_calls and conv_calls[0][0] == "make it $150/day in Tashkent"
    assert conv_calls[0][1]["operator_key"] == "tg:1001"

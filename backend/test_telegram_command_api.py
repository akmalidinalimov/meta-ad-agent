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


def _seed_members(monkeypatch, tmp_path, *, owner_user_id=None, owner_username=None,
                  admin_user_ids=None, members=None):
    """Point the RBAC members store at an isolated tmp file and seed it.

    Either pass explicit ``members`` records, or let members_store seed itself from
    TELEGRAM_ADMIN_CHAT_ID / TELEGRAM_ALLOWED_USER_IDS on first read.
    """
    import json

    path = tmp_path / "members.json"
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(path))
    if members is not None:
        path.write_text(json.dumps(members), encoding="utf-8")
        return path
    if owner_user_id is not None:
        monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", str(owner_user_id))
    if owner_username is not None:
        path.write_text(
            json.dumps([{"userId": None, "username": owner_username, "role": "owner",
                         "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}]),
            encoding="utf-8",
        )
        return path
    if admin_user_ids is not None:
        monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", str(admin_user_ids))
    return path


def _make_async(fn):
    """Wrap a sync function as an async one so it can stand in for agentic_reply
    (which the router awaits via asyncio.run)."""

    async def _wrapped(*args, **kwargs):
        return fn(*args, **kwargs)

    return _wrapped


def bind_tmp_command_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    sent = []
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "1001")
    # RBAC gate: isolate the members store to tmp and seed the test caller (user
    # 2002 / @akmal, posting from chat 1001) as a manager so the existing flows
    # stay authorized without weakening the production role gate.
    _seed_members(monkeypatch, tmp_path, owner_user_id="1001", admin_user_ids="2002")
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


def test_telegram_free_text_routes_to_agentic_brain(monkeypatch, tmp_path):
    """Free text (question or action) goes through the agentic tool-use brain and its
    answer is sent back as HTML."""
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: None)

    calls = []
    monkeypatch.setattr(
        agentic_chat,
        "agentic_reply",
        _make_async(lambda message, *, operator_key: calls.append((message, operator_key)) or "We spent $42 today — CPL $0.08, healthy."),
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "how are we doing today?",
            }
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["agentic"] is True
    assert calls and calls[0][0] == "how are we doing today?"
    assert calls[0][1] == "tg:1001"
    assert sent[-1][0] == "We spent $42 today — CPL $0.08, healthy."
    assert sent[-1][1]["parse_mode"] == "HTML"
    # A read/answer (no pending stashed) carries no inline approve buttons.
    assert sent[-1][1].get("reply_markup") is None


def test_telegram_free_text_proposal_attaches_approve_buttons(monkeypatch, tmp_path):
    """When the agentic loop stashes a pending proposal, the reply carries inline
    Approve/Reject buttons (agap:approve / agap:reject)."""
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")

    state = {"pending": None}
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: state["pending"])

    def fake_reply(message, *, operator_key):
        state["pending"] = {"kind": "agentic", "action": "set_status", "label": "Income VSL"}
        return "Activate Income VSL? Reply approve to go live."

    monkeypatch.setattr(agentic_chat, "agentic_reply", _make_async(fake_reply))

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "turn on the income campaign",
            }
        },
    )

    assert response.status_code == 200
    markup = sent[-1][1]["reply_markup"]
    buttons = markup["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "agap:approve"
    assert buttons[1]["callback_data"] == "agap:reject"


def test_telegram_text_approve_executes_pending_agentic(monkeypatch, tmp_path):
    """Typing "approve" with a pending agentic action runs execute_pending and clears it."""
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")

    pending = {"kind": "agentic", "action": "set_status", "level": "campaign", "id": "c1",
               "status": "ACTIVE", "label": "Income VSL"}
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: pending)
    cleared = []
    monkeypatch.setattr(pending_store, "clear_pending", lambda op_key, **kw: cleared.append(op_key))

    exec_calls = []
    monkeypatch.setattr(
        agentic_chat,
        "execute_pending",
        lambda p, op_key: exec_calls.append((p, op_key)) or "✅ Activated Income VSL — now live.",
    )
    # agentic_reply must NOT be called when an affirmation resolves a pending action.
    monkeypatch.setattr(
        agentic_chat,
        "agentic_reply",
        _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not reach the model"))),
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "message": {
                "chat": {"id": 1001},
                "from": {"id": 2002, "username": "akmal"},
                "text": "approve",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["agenticApproved"] is True
    assert exec_calls and exec_calls[0][1] == "tg:1001"
    assert cleared == ["tg:1001"]
    assert "Activated Income VSL" in sent[-1][0]


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
    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
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

    # RBAC gate: an unknown caller is denied access (no role) — the request is
    # accepted (200) but refused with a no-access message instead of a 403.
    assert response.status_code == 200
    assert response.json()["denied"] == "no_access"
    assert "don't have access" in sent[-1][0]


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


def test_telegram_agap_approve_callback_executes_pending(monkeypatch, tmp_path):
    """Tapping the inline Approve button (agap:approve) on an agentic proposal runs
    execute_pending, clears the pointer, and removes the buttons."""
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store
    import backend.routers.telegram as telegram_router

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")

    pending = {"kind": "agentic", "action": "create", "approvalId": "appr_1", "label": "AI Test"}
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: pending)
    cleared = []
    monkeypatch.setattr(pending_store, "clear_pending", lambda op_key, **kw: cleared.append(op_key))
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    edits = []
    monkeypatch.setattr(
        telegram_outbound,
        "edit_message_reply_markup",
        lambda *a, **k: edits.append((a, k)) or {"ok": True},
    )
    exec_calls = []
    monkeypatch.setattr(
        agentic_chat,
        "execute_pending",
        lambda p, op_key: exec_calls.append((p, op_key)) or "✅ Created PAUSED: AI Test.",
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "callback_query": {
                "id": "cbq1",
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}, "message_id": 55},
                "data": "agap:approve",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["agenticApproved"] is True
    assert exec_calls and exec_calls[0][1] == "tg:1001"
    assert cleared == ["tg:1001"]
    assert edits  # buttons removed
    assert "Created PAUSED" in sent[-1][0]


def test_telegram_agap_reject_callback_clears_pending(monkeypatch, tmp_path):
    """Tapping Reject (agap:reject) cancels the proposal without executing anything."""
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    _, sent = bind_tmp_command_store(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "secret")

    pending = {"kind": "agentic", "action": "set_status", "label": "Income VSL"}
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: pending)
    cleared = []
    monkeypatch.setattr(pending_store, "clear_pending", lambda op_key, **kw: cleared.append(op_key))
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(telegram_outbound, "edit_message_reply_markup", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        agentic_chat,
        "execute_pending",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("reject must not execute")),
    )

    client = TestClient(app)
    response = client.post(
        "/api/telegram/command",
        headers={"x-telegram-agent-secret": "secret"},
        json={
            "callback_query": {
                "id": "cbq2",
                "from": {"id": 2002, "username": "akmal"},
                "message": {"chat": {"id": 1001}, "message_id": 60},
                "data": "agap:reject",
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["agenticRejected"] is True
    assert cleared == ["tg:1001"]
    assert sent[-1][0] == "Cancelled."

"""RBAC role gate for the Telegram command surface (Task 3).

The gate resolves the caller's role from the managed members store and:
  - denies users with no role (no-access message),
  - blocks viewers from write actions and free-text requests (viewer notice),
  - lets managers (owner/admin) reach the agentic brain as before.

Each test isolates MEMBERS_STORE_PATH + PENDING_CONTEXT_STORE_PATH to a tmp dir
and seeds owner id 42, mirroring the other telegram suites.
"""

import importlib
import json

from fastapi.testclient import TestClient


def _make_async(fn):
    async def _wrapped(*args, **kwargs):
        return fn(*args, **kwargs)

    return _wrapped


def _bind(monkeypatch, tmp_path, members):
    """Isolate the RBAC + pending stores to tmp, seed members, and mock outbound.

    Returns (client, sent) where ``sent`` collects (text, kwargs) tuples.
    """
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    members_path = tmp_path / "members.json"
    members_path.write_text(json.dumps(members), encoding="utf-8")

    monkeypatch.setenv("MEMBERS_STORE_PATH", str(members_path))
    monkeypatch.setenv("PENDING_CONTEXT_STORE_PATH", str(storage / "pending_context.json"))
    # "" (not delenv): load_dotenv(override=False) won't overwrite a present-but-empty
    # value, so the secret gate stays open no matter the test collection order.
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)

    # Reload the store + access_control so they pick up the fresh env / file, then
    # the app (its router imports access_control at module scope).
    import backend.members_store as members_store
    import backend.access_control as access_control

    importlib.reload(members_store)
    importlib.reload(access_control)

    import backend.telegram_outbound as telegram_outbound

    sent = []
    monkeypatch.setattr(
        telegram_outbound,
        "send_telegram_message_sync",
        lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(telegram_outbound, "edit_message_reply_markup", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_outbound,
        "edit_message_text",
        lambda *a, **k: {"ok": True},
    )

    from backend.app import app

    return TestClient(app), sent


def _owner():
    return [{"userId": "42", "username": "owner", "role": "owner",
             "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}]


def test_unknown_user_is_denied(monkeypatch, tmp_path):
    client, sent = _bind(monkeypatch, tmp_path, _owner())
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 9999}, "from": {"id": 9999, "username": "stranger"}, "text": "/status"}},
    )
    assert resp.status_code == 200
    assert resp.json()["denied"] == "no_access"
    assert any("access" in text.lower() for text, _ in sent)


def test_viewer_free_text_is_blocked(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "7", "username": "vicky", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent = _bind(monkeypatch, tmp_path, members)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 7}, "from": {"id": 7, "username": "vicky"}, "text": "scale my best campaign"}},
    )
    assert resp.status_code == 200
    assert resp.json()["denied"] == "viewer_chat"
    assert any("viewer" in text.lower() for text, _ in sent)


def test_viewer_read_button_still_works(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "7", "username": "vicky", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent = _bind(monkeypatch, tmp_path, members)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 7}, "from": {"id": 7, "username": "vicky"}, "text": "📈 Status"}},
    )
    assert resp.status_code == 200
    assert resp.json()["menu"] == "status"
    assert any("Agent status" in text for text, _ in sent)


def test_viewer_write_callback_is_blocked(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "7", "username": "vicky", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent = _bind(monkeypatch, tmp_path, members)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"id": "cb1", "from": {"id": 7, "username": "vicky"},
                                 "message": {"chat": {"id": 7}, "message_id": 5}, "data": "approve:appr_1"}},
    )
    assert resp.status_code == 200
    assert resp.json()["denied"] == "viewer_action"
    assert any("viewer" in text.lower() for text, _ in sent)


def test_normalize_uses_callback_clicker_not_message_author():
    """Root cause: in a real Telegram callback_query, the clicker is in
    callback_query.from while callback_query.message.from is the BOT that
    authored the message. normalize must attribute the action to the clicker."""
    from backend.telegram_commands import normalize_telegram_command

    cmd = normalize_telegram_command(
        {
            "callback_query": {
                "from": {"id": 42, "username": "owner"},
                "message": {
                    "chat": {"id": 42},
                    "from": {"id": 999999, "is_bot": True, "username": "the_bot"},
                },
                "data": "agap:approve",
            }
        }
    )
    assert cmd["userId"] == "42"
    assert cmd["username"] == "owner"


def test_owner_button_press_is_authorized(monkeypatch, tmp_path):
    """Regression: a real Telegram callback_query carries the clicker in
    callback_query.from, while callback_query.message.from is the BOT that
    authored the proposal message. The identity gate must use the clicker, not
    the bot — otherwise every inline button (Approve/Reject, drill-downs) denies
    even the owner with 'no access'. (The earlier callback test omitted
    message.from, so it never exercised this real-world shape.)"""
    client, sent = _bind(monkeypatch, tmp_path, _owner())
    resp = client.post(
        "/api/telegram/command",
        json={
            "callback_query": {
                "id": "cb1",
                "from": {"id": 42, "username": "owner"},  # the human who tapped
                "message": {
                    "chat": {"id": 42},
                    "message_id": 5,
                    "from": {"id": 999999, "is_bot": True, "username": "the_bot"},  # bot authored it
                },
                "data": "agap:approve",
            }
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("denied") != "no_access"
    assert not any("access to this bot" in text.lower() for text, _ in sent)


def test_owner_free_text_reaches_agentic(monkeypatch, tmp_path):
    client, sent = _bind(monkeypatch, tmp_path, _owner())

    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: None)
    monkeypatch.setattr(agentic_chat, "agentic_reply", _make_async(lambda message, *, operator_key: "ok"))

    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 42}, "from": {"id": 42, "username": "owner"}, "text": "how are we doing?"}},
    )
    assert resp.status_code == 200
    assert resp.json()["agentic"] is True
    assert any(text == "ok" for text, _ in sent)

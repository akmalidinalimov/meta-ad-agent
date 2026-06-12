"""Team admin panel over Telegram (Task 4): owner adds/removes/role-flips members.

The owner (id 42) drives the panel; the members store is isolated to a tmp file
and the pending-context store is backed by an in-memory dict so the two-step
"➕ Add member" flow (tap, then text the member spec) runs end to end.
"""

import importlib
import json

from fastapi.testclient import TestClient


def _bind(monkeypatch, tmp_path, members):
    members_path = tmp_path / "members.json"
    members_path.write_text(json.dumps(members), encoding="utf-8")
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(members_path))
    monkeypatch.delenv("TELEGRAM_COMMAND_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)

    import backend.members_store as members_store
    import backend.access_control as access_control

    importlib.reload(members_store)
    importlib.reload(access_control)

    # In-memory pending store so the team_add two-step flow round-trips in tmp.
    import backend.pending_context_store as pending_store

    store: dict = {}
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: store.get(op_key))
    monkeypatch.setattr(pending_store, "set_pending", lambda op_key, pointer, **kw: store.__setitem__(op_key, pointer) or pointer)
    monkeypatch.setattr(pending_store, "clear_pending", lambda op_key, **kw: store.pop(op_key, None))

    import backend.telegram_outbound as telegram_outbound

    sent = []
    monkeypatch.setattr(
        telegram_outbound,
        "send_telegram_message_sync",
        lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(telegram_outbound, "edit_message_reply_markup", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(telegram_outbound, "edit_message_text", lambda *a, **k: {"ok": True})

    from backend.app import app

    return TestClient(app), sent, members_store, members_path


def _owner():
    return [{"userId": "42", "username": "owner", "role": "owner",
             "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}]


def _post(client, payload):
    return client.post("/api/telegram/command", json=payload)


def test_owner_adds_member_via_callback_then_text(monkeypatch, tmp_path):
    client, sent, members_store, _ = _bind(monkeypatch, tmp_path, _owner())

    # Step 1: tap ➕ Add member -> prompt + pending pointer stashed.
    resp = _post(client, {"callback_query": {"id": "cb1", "from": {"id": 42, "username": "owner"},
                                             "message": {"chat": {"id": 42}, "message_id": 1}, "data": "team:add"}})
    assert resp.status_code == 200
    assert resp.json()["team"] == "add_prompt"

    # Step 2: text the new member spec -> stored as admin.
    resp = _post(client, {"message": {"chat": {"id": 42}, "from": {"id": 42, "username": "owner"}, "text": "@alice admin"}})
    assert resp.status_code == 200
    assert resp.json()["team"] == "added"

    role = access_module().role_for(None, "alice")
    assert role == "admin"
    assert any("Added" in text for text, _ in sent)


def test_owner_removes_member(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "100", "username": "bob", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent, members_store, _ = _bind(monkeypatch, tmp_path, members)

    resp = _post(client, {"callback_query": {"id": "cb2", "from": {"id": 42, "username": "owner"},
                                             "message": {"chat": {"id": 42}, "message_id": 1}, "data": "team:remove:100"}})
    assert resp.status_code == 200
    assert resp.json()["team"] == "list"
    assert access_module().role_for("100", "bob") is None
    assert any("Removed" in text for text, _ in sent)


def test_owner_setrole_flips_member(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "100", "username": "bob", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent, members_store, _ = _bind(monkeypatch, tmp_path, members)

    resp = _post(client, {"callback_query": {"id": "cb3", "from": {"id": 42, "username": "owner"},
                                             "message": {"chat": {"id": 42}, "message_id": 1}, "data": "team:setrole:100~admin"}})
    assert resp.status_code == 200
    assert access_module().role_for("100", "bob") == "admin"
    assert any("Role set to admin" in text for text, _ in sent)


def test_owner_cannot_remove_owner(monkeypatch, tmp_path):
    client, sent, members_store, _ = _bind(monkeypatch, tmp_path, _owner())

    resp = _post(client, {"callback_query": {"id": "cb4", "from": {"id": 42, "username": "owner"},
                                             "message": {"chat": {"id": 42}, "message_id": 1}, "data": "team:remove:42"}})
    assert resp.status_code == 200
    # Still owner, and a guard message was sent.
    assert access_module().role_for("42", "owner") == "owner"
    assert any("owner" in text.lower() for text, _ in sent)


def access_module():
    import backend.access_control as access_control

    return access_control

"""Guided campaign creation — Telegram callback dispatch (Task 5 integration).

These tests drive the guided flow through ``/api/telegram/command`` and assert the
RBAC-clean dispatch + correct routing (no ``no_access``, the right transport calls
fire). The state-machine logic itself is owned by ``test_guided_campaign.py``; here
we only prove the callbacks reach ``_handle_guided`` and move the flow forward.

Store alignment: the app's router reads the pending store via the module-level
``pending_context_store`` functions (whose ``storage_dir`` default is the real
``STORAGE_DIR``). To stay hermetic we point that store at a tmp dir by patching the
store functions to inject a tmp ``storage_dir``, and seed the guided state through
the SAME redirected store so ``start`` and the router agree on where it lives.
"""

import importlib
import json

from fastapi.testclient import TestClient


def _owner():
    return [{"userId": "42", "username": "owner", "role": "owner",
             "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}]


def _bind(monkeypatch, tmp_path, members):
    """Isolate RBAC + the pending store to tmp, seed members, mock outbound.

    Returns (client, sent, media, edits, store_dir) where:
      - ``sent`` collects (text, kwargs) from send_telegram_message_sync,
      - ``media`` collects ("photo"|"video", chat_id, url) tuples,
      - ``edits`` collects edit_message_reply_markup calls,
      - ``store_dir`` is the tmp dir the pending store is redirected to.
    """
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    members_path = tmp_path / "members.json"
    members_path.write_text(json.dumps(members), encoding="utf-8")

    monkeypatch.setenv("MEMBERS_STORE_PATH", str(members_path))
    # Set to "" (not delenv): config/telegram_outbound call load_dotenv() lazily at
    # import; with override=False it won't overwrite an already-present empty value,
    # so the secret gate stays open regardless of test collection order. delenv would
    # be silently re-populated from the repo .env on a later first-time import → 401.
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)

    import backend.members_store as members_store
    import backend.access_control as access_control

    importlib.reload(members_store)
    importlib.reload(access_control)

    # Redirect the pending store to the tmp dir. Two bindings must agree:
    #  (1) the router late-imports get_pending/set_pending from pending_context_store
    #      directly (free-text branch, op_key), and
    #  (2) guided_campaign imported get_pending/set_pending at module load and calls
    #      them WITHOUT a storage_dir (so it would otherwise use the real STORAGE_DIR).
    # Patch BOTH so seeding + every guided read/write hit the same tmp file.
    import backend.pending_context_store as pcs
    import backend.guided_campaign as gc

    _real_get, _real_set, _real_clear = pcs.get_pending, pcs.set_pending, pcs.clear_pending

    def _get(op_key, *, storage_dir=None):
        return _real_get(op_key, storage_dir=storage)

    def _set(op_key, pointer, *, storage_dir=None):
        return _real_set(op_key, pointer, storage_dir=storage)

    def _clear(op_key, *, storage_dir=None):
        return _real_clear(op_key, storage_dir=storage)

    for mod in (pcs, gc):
        monkeypatch.setattr(mod, "get_pending", _get, raising=False)
        monkeypatch.setattr(mod, "set_pending", _set, raising=False)
        monkeypatch.setattr(mod, "clear_pending", _clear, raising=False)

    import backend.telegram_outbound as telegram_outbound

    sent = []
    media = []
    edits = []
    monkeypatch.setattr(
        telegram_outbound, "send_telegram_message_sync",
        lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_outbound, "edit_message_reply_markup",
        lambda *a, **k: edits.append((a, k)) or {"ok": True},
    )
    monkeypatch.setattr(telegram_outbound, "edit_message_text", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_outbound, "send_photo",
        lambda chat_id, photo, **k: media.append(("photo", chat_id, photo)) or {"ok": True},
    )
    monkeypatch.setattr(
        telegram_outbound, "send_video",
        lambda chat_id, video, **k: media.append(("video", chat_id, video)) or {"ok": True},
    )

    from backend.app import app

    return TestClient(app), sent, media, edits, storage


def _seed_guided(storage_dir):
    """Start the guided flow for owner 42 in the SAME store the app reads."""
    from backend import guided_campaign
    from backend.pending_context_store import operator_key

    op_key = operator_key(telegram_chat_id="42")
    guided_campaign.start(op_key, storage_dir=storage_dir)
    return op_key


def _knowledge_with_creatives():
    return {"analysis": {"topAds": [
        {"name": "Ad A", "creative": {"id": "cr_1", "thumbnail_url": "http://t/1.jpg"}},
        {"name": "Ad B", "creative": {"id": "cr_2", "image_url": "http://t/2.jpg"}},
    ]}}


def _callback(data, *, chat=42, user=42, username="owner"):
    # Realistic Telegram callback: callback_query.from is the human clicker, while
    # callback_query.message.from is the BOT (exercises the RBAC clicker fix).
    return {"callback_query": {
        "id": "cb1",
        "from": {"id": user, "username": username},
        "message": {
            "chat": {"id": chat},
            "message_id": 5,
            "from": {"id": 999, "is_bot": True, "username": "the_bot"},
        },
        "data": data,
    }}


def test_create_campaign_freetext_shows_audience_buttons(monkeypatch, tmp_path):
    """Entry seam: typing 'create a campaign' makes the model call the tool, which
    opens the guided flow (guided_create pending). The router must surface the
    audience question WITH its three gcreate buttons — the model's text answer does
    not carry the keyboard."""
    client, sent, media, edits, storage = _bind(monkeypatch, tmp_path, _owner())

    import backend.agentic_chat as agentic_chat
    from backend import guided_campaign

    async def fake_reply(message, *, operator_key):
        guided_campaign.start(operator_key)  # what the create_test_campaign tool does
        return "Let's set that up."

    monkeypatch.setattr(agentic_chat, "agentic_reply", fake_reply, raising=False)

    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 42}, "from": {"id": 42, "username": "owner"},
                          "text": "create a test campaign"}},
    )
    assert resp.status_code == 200
    cbs = []
    for _text, kw in sent:
        for row in (kw.get("reply_markup") or {}).get("inline_keyboard", []):
            cbs += [b.get("callback_data") for b in row]
    assert {"gcreate:aud:proven", "gcreate:aud:new", "gcreate:aud:input"} <= set(cbs)


def test_audience_new_callback_renders_creatives(monkeypatch, tmp_path):
    client, sent, media, edits, storage = _bind(monkeypatch, tmp_path, _owner())
    _seed_guided(storage)

    import backend.guided_campaign as gc
    monkeypatch.setattr(gc, "_load_knowledge", lambda: _knowledge_with_creatives(), raising=False)
    import backend.knowledge_base as kb
    monkeypatch.setattr(kb, "load_knowledge_base", lambda: _knowledge_with_creatives())

    resp = client.post("/api/telegram/command", json=_callback("gcreate:aud:new"))
    assert resp.status_code == 200
    body = resp.json()
    # RBAC-clean: the owner is never denied.
    assert body.get("denied") != "no_access"
    # Routing: the creative picker was rendered (media sent + a "pick" control msg).
    assert body.get("guided") == "creatives"
    assert any(kind == "photo" for kind, _chat, _url in media)
    assert any("Tap" in text and "confirm" in text.lower() for text, _ in sent)


def test_creative_toggle_callback_edits_keyboard(monkeypatch, tmp_path):
    client, sent, media, edits, storage = _bind(monkeypatch, tmp_path, _owner())
    op_key = _seed_guided(storage)
    # Advance to the creatives step so a toggle is meaningful.
    from backend import guided_campaign
    guided_campaign.handle_audience_choice(op_key, "proven", storage_dir=storage)

    resp = client.post("/api/telegram/command", json=_callback("gcreate:cre:toggle:cr_1"))
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("denied") != "no_access"
    assert body.get("guided") == "toggle"
    assert body.get("selected") == ["cr_1"]
    # The tapped message's keyboard was rewritten with the flipped label.
    assert edits, "expected edit_message_reply_markup to be called"


def test_guided_callback_blocked_for_viewer(monkeypatch, tmp_path):
    members = _owner() + [{"userId": "7", "username": "vicky", "role": "viewer",
                           "addedBy": "42", "addedAt": "2026-01-02T00:00:00+00:00"}]
    client, sent, media, edits, storage = _bind(monkeypatch, tmp_path, members)

    resp = client.post(
        "/api/telegram/command",
        json=_callback("gcreate:aud:new", chat=7, user=7, username="vicky"),
    )
    assert resp.status_code == 200
    assert resp.json()["denied"] == "viewer_action"

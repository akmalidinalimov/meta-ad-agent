import os

from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
from backend.app import app


def _seed_owner(monkeypatch, username="a"):
    """RBAC gate: isolate the members store and seed the test caller (@a) as owner."""
    import json
    import tempfile

    fd, path = tempfile.mkstemp(suffix="_members.json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            [{"userId": None, "username": username, "role": "owner",
              "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}],
            fh,
        )
    monkeypatch.setenv("MEMBERS_STORE_PATH", path)

APPROVAL_ID = "approval_20260101T000000Z"


def _approvals():
    return [
        {
            "id": APPROVAL_ID,
            "status": "needs_review",
            "risk": "low",
            "actionType": "create_campaign",
            "after": {
                "campaign": {"name": "Q3 Scale Test"},
                "adsets": [
                    {
                        "name": "Broad 25-45",
                        "status": "PAUSED",
                        "daily_budget": "3000",
                        "optimization_goal": "OFFSITE_CONVERSIONS",
                        "targeting": {"geo_locations": {"countries": ["US", "CA"]}},
                        "ads": [
                            {"name": "Carousel A", "creativeId": "creative_777", "status": "PAUSED"},
                        ],
                    }
                ],
            },
        },
        {"id": "approval_other", "status": "approved", "after": {"campaign": {"name": "Already done"}}},
    ]


def _open_bot(monkeypatch):
    for var in ("TELEGRAM_COMMAND_SECRET", "TELEGRAM_ALLOWED_CHAT_IDS", "TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ADMIN_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    _seed_owner(monkeypatch)
    sent = []
    edits = []
    monkeypatch.setattr(telegram_outbound, "send_telegram_message_sync", lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True})
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_outbound,
        "edit_message_text",
        lambda chat_id, message_id, text, **kwargs: edits.append((text, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(telegram_router, "list_approval_requests", _approvals)
    return sent, edits


def test_pending_reply_button_shows_campaign_picker(monkeypatch):
    sent, _ = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "📝 Pending Approvals"}},
    )
    assert resp.status_code == 200
    assert resp.json()["menu"] == "pending"
    markup = next(kwargs["reply_markup"] for _, kwargs in sent if "reply_markup" in kwargs)
    data = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
    # The needs_review approval has no campaign id -> the "none" bucket; the approved
    # (non-pending) one is excluded entirely.
    assert data == ["apv:gc:none"]
    assert any("Q3 Scale Test" in label for label in labels)


def test_pending_campaign_drill_lists_only_its_needs_review(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": "apv:gc:none"}},
    )
    assert resp.status_code == 200
    assert resp.json()["pending"] == "campaign"
    markup = next(kwargs["reply_markup"] for _, kwargs in edits if "reply_markup" in kwargs)
    data = [b.get("callback_data") for row in markup["inline_keyboard"] for b in row]
    assert f"apv:a:{APPROVAL_ID}" in data
    assert all("approval_other" not in (cd or "") for cd in data)
    assert "apv:list" in data  # Back to the campaign picker


def test_approval_callback_shows_adsets(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": f"apv:a:{APPROVAL_ID}"}},
    )
    assert resp.status_code == 200
    assert resp.json()["approval"] == APPROVAL_ID
    # Ad set names live in the inline keyboard buttons; callbacks drill by index.
    markup = next(kwargs["reply_markup"] for _, kwargs in edits if "reply_markup" in kwargs)
    labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
    data = [b.get("callback_data") for row in markup["inline_keyboard"] for b in row]
    assert any("Broad 25-45" in label for label in labels)
    assert f"apv:s:{APPROVAL_ID}~0" in data


def test_approval_adset_leaf_shows_creative_lines(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": f"apv:s:{APPROVAL_ID}~0"}},
    )
    assert resp.status_code == 200
    assert resp.json()["adset"] == 0
    text = next(t for t, _ in edits)
    assert "Carousel A" in text
    assert "creative_777" in text
    assert "US, CA" in text  # targeting summary


def test_missing_approval_is_friendly(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": "apv:a:does_not_exist"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert any("no longer pending" in text for text, _ in edits)


def test_bad_index_is_guarded(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": f"apv:s:{APPROVAL_ID}~99"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert any("no longer available" in text for text, _ in edits)


def test_manage_approve_button_applies_immediately(monkeypatch):
    sent, _ = _open_bot(monkeypatch)
    manage = {
        "id": "manage_tg",
        "status": "needs_review",
        "actionType": "manage_campaigns",
        "risk": "medium",
        "after": {"status": "ARCHIVED", "campaigns": [{"id": "cmp_a", "name": "Old A", "effective_status": "PAUSED"}]},
    }
    monkeypatch.setattr(telegram_router, "list_approval_requests", lambda: [manage])

    approved = []
    import backend.approval_store as approval_store

    monkeypatch.setattr(approval_store, "approve_request", lambda approval_id, **k: approved.append(approval_id) or manage)
    monkeypatch.setattr(
        telegram_router,
        "apply_live_sync",
        lambda approval_id: {"ok": True, "result": {"ok": True, "status": "ARCHIVED", "changed": [{"id": "cmp_a"}]}},
    )
    monkeypatch.setattr(telegram_outbound, "edit_message_reply_markup", lambda *a, **k: {"ok": True})

    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 9}, "from": {"username": "a"}, "data": "approve:manage_tg"}},
    )
    assert resp.status_code == 200
    assert resp.json()["managed"] is True
    assert approved == ["manage_tg"]
    assert any("Archived 1 campaign" in text for text, _ in sent)

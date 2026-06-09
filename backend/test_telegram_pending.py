from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
from backend.app import app

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


def test_pending_reply_button_lists_only_needs_review(monkeypatch):
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
    assert f"apv:a:{APPROVAL_ID}" in data
    # The approved (non-pending) approval is excluded.
    assert all("approval_other" not in cd for cd in data)


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

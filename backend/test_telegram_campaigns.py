from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
from backend.app import app

LONG_CAMPAIGN_ID = "120200000000000001"
LONG_ADSET_ID = "238400000000000002"


def _account():
    return {
        "campaigns": [
            {"id": LONG_CAMPAIGN_ID, "name": "Spring Promo", "status": "ACTIVE", "objective": "OUTCOME_SALES"},
            {"id": "120200000000000099", "name": "Old Brand", "status": "PAUSED"},
        ],
        "adsets": [
            {
                "id": LONG_ADSET_ID,
                "name": "Lookalike 1%",
                "campaign_id": LONG_CAMPAIGN_ID,
                "status": "ACTIVE",
                "daily_budget": "5000",
                "optimization_goal": "OFFSITE_CONVERSIONS",
            }
        ],
        "ads": [
            {
                "id": "238500000000000003",
                "name": "Hero Video Ad",
                "adset_id": LONG_ADSET_ID,
                "status": "ACTIVE",
                "creative": {
                    "id": "cr_1",
                    "name": "Hero creative",
                    "title": "Save 30% today",
                    "body": "Limited time spring offer on everything in store.",
                    "thumbnail_url": "https://example.com/thumb.jpg",
                    "video_id": "vid123",
                },
            }
        ],
        "account_id": "act_555",
        "source": "live",
    }


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
    monkeypatch.setattr(telegram_router, "_live_account_sync", _account)
    return sent, edits


def test_campaigns_reply_button_sends_list(monkeypatch):
    sent, _ = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "📁 Campaigns"}},
    )
    assert resp.status_code == 200
    assert resp.json()["menu"] == "campaigns"
    assert any("Campaigns" in text for text, _ in sent)
    # The campaigns keyboard is attached with the right callbacks.
    markup = next(kwargs["reply_markup"] for _, kwargs in sent if "reply_markup" in kwargs)
    data = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
    assert f"cmp:c:{LONG_CAMPAIGN_ID}" in data


def test_campaign_callback_edits_to_adsets(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 7}, "from": {"username": "a"}, "data": f"cmp:c:{LONG_CAMPAIGN_ID}"}},
    )
    assert resp.status_code == 200
    assert resp.json()["campaign"] == LONG_CAMPAIGN_ID
    # Ad set names live in the inline keyboard buttons; callbacks drill to cmp:s:<id>.
    markup = next(kwargs["reply_markup"] for _, kwargs in edits if "reply_markup" in kwargs)
    labels = [b["text"] for row in markup["inline_keyboard"] for b in row]
    data = [b.get("callback_data") for row in markup["inline_keyboard"] for b in row]
    assert any("Lookalike 1%" in label for label in labels)
    assert f"cmp:s:{LONG_ADSET_ID}" in data


def test_adset_callback_renders_creative_detail(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 7}, "from": {"username": "a"}, "data": f"cmp:s:{LONG_ADSET_ID}"}},
    )
    assert resp.status_code == 200
    assert resp.json()["adset"] == LONG_ADSET_ID
    text = next(t for t, _ in edits)
    assert "Hero Video Ad" in text
    assert "Save 30% today" in text  # creative title
    assert "vid123" in text  # video link
    assert "adsmanager.facebook.com" in text  # Ads Manager link
    assert "act=555" in text


def test_snapshot_source_annotates_as_of_last_sync(monkeypatch):
    sent, _ = _open_bot(monkeypatch)
    account = _account()
    account["source"] = "snapshot"
    monkeypatch.setattr(telegram_router, "_live_account_sync", lambda: account)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "📁 Campaigns"}},
    )
    assert resp.status_code == 200
    assert any("as of last sync" in text for text, _ in sent)

from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
from backend.app import app

LONG_CAMPAIGN_ID = "120200000000000001"
LONG_ADSET_ID = "238400000000000002"


def _account():
    return {
        "campaigns": [
            {
                "id": LONG_CAMPAIGN_ID,
                "name": "Spring Promo",
                "status": "ACTIVE",
                "objective": "OUTCOME_SALES",
                "buying_type": "AUCTION",
                "daily_budget": "20000",
            },
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
                "billing_event": "IMPRESSIONS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "is_dynamic_creative": True,
                "targeting": {
                    "age_min": 25,
                    "age_max": 44,
                    "geo_locations": {"cities": [{"name": "Tashkent"}]},
                    "publisher_platforms": ["instagram", "facebook"],
                    "instagram_positions": ["reels", "story"],
                    "flexible_spec": [
                        {"interests": [{"name": f"Interest {i}"} for i in range(20)]}
                    ],
                    "custom_audiences": [{"id": "ca_77"}],
                },
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
        "adstudies": [
            {
                "id": "study_1",
                "name": "Spring A/B",
                "cells": {"data": [{"adsets": {"data": [{"id": LONG_ADSET_ID, "campaign_id": LONG_CAMPAIGN_ID}]}}]},
            }
        ],
        "saved_audiences": [{"id": "ca_77", "name": "Past Buyers"}],
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
    # The ad-set leaf fetches its creatives scoped to the ad set; stub that seam to
    # return the account's ads for the requested ad set (ranked, no insights).
    monkeypatch.setattr(
        telegram_router,
        "_adset_creatives_sync",
        lambda sid: ([a for a in _account()["ads"] if str(a.get("adset_id")) == str(sid)], "live"),
    )
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
    # The campaign detail text now shows buying type, an A/B indicator, and campaign budget.
    text = next(t for t, _ in edits)
    assert "Buying type: AUCTION" in text
    assert "A/B test: enabled (Spring A/B)" in text
    assert "Daily budget: $200.00" in text
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
    # Thumbnails/video now live in the web app (View creatives button); the chat
    # message stays compact and points there.
    assert "View creatives" in text
    assert "adsmanager.facebook.com" in text  # Ads Manager link
    assert "act=555" in text
    # New config fields: interests/placements/age/geo/custom-audience names/billing-bid/DCO.
    assert "Age: 25-44" in text
    assert "Tashkent" in text
    assert "Interest 0" in text
    assert "+12 more" in text  # interest list truncated to 8 of 20
    assert "instagram" in text
    assert "Past Buyers" in text  # custom-audience id ca_77 resolved to name
    assert "Billing/bid: IMPRESSIONS / LOWEST_COST_WITHOUT_CAP" in text
    assert "Dynamic creative (DCO): on" in text
    # Stays well under Telegram's 4096-char limit.
    assert len(text) < 4096


def test_adset_detail_resolves_custom_audience_id_fallback(monkeypatch):
    # When the saved-audience map has no name, the raw id is shown (no crash).
    _, edits = _open_bot(monkeypatch)
    account = _account()
    account["saved_audiences"] = []  # force fallback to id
    monkeypatch.setattr(telegram_router, "_live_account_sync", lambda: account)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 7}, "from": {"username": "a"}, "data": f"cmp:s:{LONG_ADSET_ID}"}},
    )
    assert resp.status_code == 200
    text = next(t for t, _ in edits)
    assert "Custom audiences: ca_77" in text


def test_rank_creatives_orders_by_results_then_ctr():
    ads = [
        {"id": "a1", "name": "Low"},
        {"id": "a2", "name": "TopResults"},
        {"id": "a3", "name": "HighCtrNoResults"},
    ]
    insights = [
        {"ad_id": "a1", "impressions": "100", "spend": "1", "ctr": "0.5", "actions": []},
        {"ad_id": "a2", "impressions": "50", "spend": "9", "ctr": "1.0",
         "actions": [{"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"}]},
        {"ad_id": "a3", "impressions": "200", "spend": "2", "ctr": "5.0", "actions": []},
    ]
    import backend.adset_creatives as ac

    ranked = ac.rank_creatives(ads, insights)
    assert [a["name"] for a in ranked] == ["TopResults", "HighCtrNoResults", "Low"]
    assert ranked[0]["_perf"]["results"] == 7
    assert ranked[0]["_perf"]["results_label"] == "leads"


def test_adset_leaf_shows_ranked_performance(monkeypatch):
    _, edits = _open_bot(monkeypatch)
    ranked = [
        {"id": "ad_top", "name": "Winner", "status": "ACTIVE",
         "creative": {"title": "Best hook"},
         "_perf": {"impressions": 1200, "spend": 45.0, "ctr": 2.1, "results": 12,
                   "results_label": "leads", "has_data": True}},
    ]
    monkeypatch.setattr(telegram_router, "_adset_creatives_sync", lambda sid: (ranked, "live"))
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 7}, "from": {"username": "a"}, "data": f"cmp:s:{LONG_ADSET_ID}"}},
    )
    assert resp.status_code == 200
    text = next(t for t, _ in edits)
    assert "best performing first" in text
    assert "12 leads" in text
    assert "2.10%" in text


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

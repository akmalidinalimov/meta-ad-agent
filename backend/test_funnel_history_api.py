"""Endpoint smoke tests for GET /api/funnel/history (sources patched — no network)."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

import backend.routers.funnel as funnel_mod
from backend.app import app


class _Cfg:
    def __init__(self, configured):
        self.is_configured = configured


def test_history_returns_not_connected_when_meta_off(monkeypatch):
    monkeypatch.setattr(funnel_mod, "get_meta_config", lambda: _Cfg(False))
    client = TestClient(app)
    resp = client.get("/api/funnel/history?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["points"] == []


def test_history_builds_daily_points(monkeypatch):
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = [
        {
            "date_start": yesterday.isoformat(),
            "campaign_id": "c1",
            "spend": 10,
            "impressions": 1000,
            "clicks": 100,
            "actions": [
                {"action_type": "link_click", "value": 80},
                {"action_type": "landing_page_view", "value": 60},
                {"action_type": "lead", "value": 40},
            ],
        },
        {
            "date_start": today.isoformat(),
            "campaign_id": "c1",
            "spend": 12,
            "impressions": 1200,
            "clicks": 120,
            "actions": [
                {"action_type": "link_click", "value": 90},
                {"action_type": "landing_page_view", "value": 70},
                {"action_type": "lead", "value": 50},
            ],
        },
    ]

    async def fake_insights(*a, **k):
        return rows

    async def fake_crm(days):
        return {yesterday.isoformat(): 3, today.isoformat(): 2}

    async def fake_vsl(days):
        return None

    monkeypatch.setattr(funnel_mod, "get_meta_config", lambda: _Cfg(True))
    monkeypatch.setattr(funnel_mod, "safe_chunked_insights", fake_insights)
    monkeypatch.setattr(
        funnel_mod,
        "load_funnel_events",
        lambda **k: [
            {"eventName": "bot_start", "receivedAt": yesterday.isoformat() + "T08:00:00Z", "telegramUserId": "A"},
            {"eventName": "bot_start", "receivedAt": yesterday.isoformat() + "T09:00:00Z", "telegramUserId": "B"},
            *[
                {"eventName": "telegram_link_click", "receivedAt": yesterday.isoformat() + "T07:00:00Z", "visitorId": f"v{i}"}
                for i in range(4)
            ],
        ],
    )
    monkeypatch.setattr(funnel_mod, "_crm_leads_by_date", fake_crm)
    monkeypatch.setattr(funnel_mod, "_vsl_views_now", fake_vsl)
    monkeypatch.setattr(funnel_mod, "record_vsl_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(funnel_mod, "load_vsl_snapshots", lambda **k: {})

    client = TestClient(app)
    resp = client.get("/api/funnel/history?campaignId=c1&days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["campaignId"] == "c1"
    assert body["granularity"] == "day"
    assert len(body["points"]) == 7  # full 7-day window, zero-filled where no data

    point = next(p for p in body["points"] if p["date"] == yesterday.isoformat())
    assert point["counts"]["landingViews"] == 60
    assert point["counts"]["leads"] == 40
    assert point["counts"]["botStarts"] == 2
    assert point["counts"]["crmLeads"] == 3
    assert point["counts"]["vslViews"] is None  # VSL not configured in this test
    assert point["startRate"] == 50.0  # 2 starts ÷ ... (button clicks present yesterday)

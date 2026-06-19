"""Live campaign list + per-campaign KPI endpoints (/api/campaigns/live, /kpis).

Meta is mocked: get_campaigns (the live campaign list) and safe_chunked_insights (live
insights) are patched, so these assert the routing + created-date filtering + KPI math,
not the network calls."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.meta_client as meta_client
import backend.routers.campaigns as campaigns_router
from backend.app import app


def _cfg():
    return SimpleNamespace(is_configured=True, ad_account_id="act_1")


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _patch_campaigns(monkeypatch, campaigns):
    async def fake_get_campaigns(config):
        return campaigns

    monkeypatch.setattr(campaigns_router, "get_meta_config", _cfg)
    monkeypatch.setattr(meta_client, "get_campaigns", fake_get_campaigns)


def test_campaigns_live_filters_by_created_within_days(monkeypatch):
    _patch_campaigns(monkeypatch, [
        {"id": "new1", "name": "DA - SHAHLOAI - VSL - 16.06.2026", "status": "ACTIVE",
         "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS", "daily_budget": "17000",
         "created_time": _iso(2), "start_time": _iso(2)},
        {"id": "old1", "name": "Old campaign", "status": "PAUSED", "effective_status": "PAUSED",
         "objective": "OUTCOME_LEADS", "created_time": _iso(40)},
        {"id": "nodate", "name": "No created date", "status": "ACTIVE"},
    ])

    body = TestClient(app).get("/api/campaigns/live?createdWithinDays=7").json()
    assert body["ok"] and body["source"] == "live"
    # Only the campaign created within 7 days; the 40-day-old and the undated ones drop out.
    assert [c["id"] for c in body["campaigns"]] == ["new1"]
    new = body["campaigns"][0]
    assert new["name"] == "DA - SHAHLOAI - VSL - 16.06.2026"
    assert new["dailyBudgetUsd"] == 170.0  # 17000 minor units / 100


def test_campaigns_live_returns_all_without_filter(monkeypatch):
    _patch_campaigns(monkeypatch, [
        {"id": "a", "name": "A", "created_time": _iso(2)},
        {"id": "b", "name": "B", "created_time": _iso(100)},
    ])
    body = TestClient(app).get("/api/campaigns/live").json()
    assert {c["id"] for c in body["campaigns"]} == {"a", "b"}


def test_campaigns_live_reports_not_connected(monkeypatch):
    monkeypatch.setattr(campaigns_router, "get_meta_config", lambda: SimpleNamespace(is_configured=False, ad_account_id=""))
    body = TestClient(app).get("/api/campaigns/live").json()
    assert body["ok"] is False and body["campaigns"] == []


_INSIGHT_ROWS = [
    {"campaign_id": "c1", "campaign_name": "Alpha", "spend": "100", "impressions": "1000", "clicks": "100",
     "actions": [{"action_type": "lead", "value": "20"}, {"action_type": "subscribe", "value": "8"}]},
    {"campaign_id": "c2", "campaign_name": "Beta", "spend": "50", "impressions": "500", "clicks": "50",
     "actions": [{"action_type": "lead", "value": "5"}]},
]


def _patch_funnel(monkeypatch, *, bot_starts=0, link_clicks=0, by_campaign=None):
    """Stub the first-party funnel-event helpers so the START-rate path is deterministic
    (campaign_kpis reads bot-starts / link-clicks from funnel_events, not Meta subscribe)."""
    monkeypatch.setattr(campaigns_router, "count_bot_starts", lambda **kw: bot_starts)
    monkeypatch.setattr(
        campaigns_router, "count_event_users",
        lambda name, **kw: link_clicks if name == "telegram_link_click" else 0,
    )
    monkeypatch.setattr(campaigns_router, "telegram_starts_by_campaign_date", lambda **kw: by_campaign or {})


def test_campaign_kpis_scopes_live_to_one_campaign(monkeypatch):
    monkeypatch.setattr(campaigns_router, "get_meta_config", _cfg)
    _patch_funnel(monkeypatch)  # no first-party starts -> START falls back to Meta subscribe/leads

    async def fake_insights(config, name, breakdowns, *, days=90, end_date=None):
        return _INSIGHT_ROWS

    monkeypatch.setattr(campaigns_router, "safe_chunked_insights", fake_insights)
    client = TestClient(app)

    body = client.get("/api/campaigns/kpis?campaignId=c1&days=30").json()
    assert body["ok"] and body["campaignId"] == "c1" and body["campaignName"] == "Alpha"
    assert body["hasData"] is True
    assert body["kpis"]["spend"] == 100.0
    assert body["kpis"]["leads"] == 20
    assert body["kpis"]["subscribes"] == 8
    assert body["rates"]["startRate"] == 40.0  # 8 Meta subscribes / 20 leads (no first-party starts)

    allbody = client.get("/api/campaigns/kpis?days=30").json()
    assert allbody["campaignId"] == "all"
    assert allbody["kpis"]["spend"] == 150.0  # both campaigns
    assert allbody["kpis"]["leads"] == 25


def test_campaign_kpis_uses_first_party_bot_starts_for_start_rate(monkeypatch):
    # The fix: START rate comes from first-party bot-starts (funnel_events), NOT the Meta
    # `subscribe` action, which is 0 for a lead-optimized account.
    monkeypatch.setattr(campaigns_router, "get_meta_config", _cfg)
    _patch_funnel(monkeypatch, bot_starts=1630, link_clicks=1710)

    async def fake_insights(config, name, breakdowns, *, days=90, end_date=None):
        return [{"campaign_id": "c1", "campaign_name": "Alpha", "spend": "100",
                 "impressions": "1000", "clicks": "100", "actions": [{"action_type": "lead", "value": "1434"}]}]

    monkeypatch.setattr(campaigns_router, "safe_chunked_insights", fake_insights)
    body = TestClient(app).get("/api/campaigns/kpis?days=30").json()
    assert body["kpis"]["subscribes"] == 0                 # Meta reports no subscribe conversion
    assert body["rates"]["startRate"] == 95.3              # 1630 bot starts / 1710 button clicks
    assert body["startSource"] == "telegram_relay"
    assert body["startDenominatorSource"] == "telegram_link_click"
    assert body["counts"]["botStarts"] == 1630 and body["counts"]["telegramLinkClicks"] == 1710


def test_campaign_kpis_zero_delivery_is_honest_zeros(monkeypatch):
    monkeypatch.setattr(campaigns_router, "get_meta_config", _cfg)
    _patch_funnel(monkeypatch)

    async def fake_insights(config, name, breakdowns, *, days=90, end_date=None):
        return _INSIGHT_ROWS  # neither row matches the requested campaign

    monkeypatch.setattr(campaigns_router, "safe_chunked_insights", fake_insights)
    body = TestClient(app).get("/api/campaigns/kpis?campaignId=c_no_delivery&days=7").json()
    assert body["ok"] and body["hasData"] is False
    assert body["kpis"]["spend"] == 0
    assert body["rates"]["visitRate"] == 0 and body["rates"]["startRate"] == 0

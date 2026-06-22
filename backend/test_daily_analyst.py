# backend/test_daily_analyst.py
import asyncio
from types import SimpleNamespace
import backend.daily_analyst as da

_ADS = [
    {"campaign_id": "c1", "campaign_name": "VSL", "adset_id": "as1", "adset_name": "LAL",
     "ad_id": "a", "ad_name": "v1", "spend": "10", "impressions": "1000", "frequency": "1.2",
     "ctr": "5", "actions": [{"action_type": "lead", "value": "20"}],
     "video_play_actions": [{"action_type": "video_view", "value": "400"}],
     "video_p75_watched_actions": [{"action_type": "video_view", "value": "200"}]},
    {"campaign_id": "c1", "campaign_name": "VSL", "adset_id": "as2", "adset_name": "Interest",
     "ad_id": "b", "ad_name": "v2", "spend": "8", "impressions": "900", "frequency": "1.0",
     "ctr": "2", "actions": [{"action_type": "lead", "value": "16"}]},
]


def test_analyze_produces_ranked_audiences_and_recs(monkeypatch):
    monkeypatch.setattr(da, "get_meta_config", lambda: SimpleNamespace(is_configured=True, ad_account_id="act_1"))

    async def fake_insights(config, **kw):
        return _ADS
    monkeypatch.setattr(da, "get_insights", fake_insights)

    # _campaign_event_map is ASYNC in the real code — monkeypatch with an async fake.
    async def fake_campaign_event_map(config):
        return {"c1": "LEAD"}
    monkeypatch.setattr(da, "_campaign_event_map", fake_campaign_event_map)

    monkeypatch.setattr(da, "count_bot_starts", lambda **kw: 30)
    monkeypatch.setattr(da, "count_event_users", lambda name, **kw: 40 if name == "telegram_link_click" else 0)
    monkeypatch.setattr(da, "load_targets", lambda: {"maxCpl": 0.8})

    async def fake_crm():
        return {"leads": 5, "stages": {}}
    monkeypatch.setattr(da, "_crm_today", fake_crm)

    analysis = asyncio.run(da.run_daily_analysis())
    assert analysis["ok"] is True
    assert [a["adsetId"] for a in analysis["audiences"]]   # ranked, non-empty
    assert "recommendations" in analysis and "rates" in analysis
    assert analysis["rates"]["cpl"] is not None

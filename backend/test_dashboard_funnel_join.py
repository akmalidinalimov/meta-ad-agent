"""End-to-end: ingested funnel events join into the live dashboard payload.

This guards the "last-mile join" — a Telegram START (bot_start) ingested via the
funnel endpoints must show up as telegramSubscribers on the matching per-(campaign,
date) metric row and as a populated funnelSummary, which is what feeds the dashboard
and the 4-hourly monitoring rules.
"""

from datetime import datetime, timezone

from backend.dashboard_service import dashboard_from_knowledge_base
from backend.funnel_events import save_funnel_event


def _knowledge(date: str) -> dict:
    base_row = {
        "date_start": date,
        "campaign_id": "cmp_1",
        "adset_id": "as_1",
        "ad_id": "ad_1",
        "spend": "100",
        "impressions": "1000",
        "clicks": "200",
        "actions": [{"action_type": "lead", "value": "40"}],
    }
    return {
        "raw": {
            "campaigns": [{"id": "cmp_1", "name": "Income VSL"}],
            "adsets": [],
            "ads": [],
            "insights": {"base": [base_row]},
        },
        "analysis": {},
        "snapshot": {"days": 90},
    }


def test_dashboard_join_populates_telegram_subscribers_and_funnel_summary(tmp_path):
    storage_dir = tmp_path / "storage"
    # In production a START and its campaign's Meta row share the day it happened; the
    # test mirrors that by stamping the metric row with today's UTC date.
    today = datetime.now(timezone.utc).date().isoformat()
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v1", "campaign_id": "cmp_1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "telegram_user_id": "t1", "campaign_id": "cmp_1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v2", "telegram_user_id": "t2", "campaign_id": "cmp_1"}, storage_dir=storage_dir)

    dashboard = dashboard_from_knowledge_base(_knowledge(today), funnel_storage_dir=storage_dir)

    rows = [r for r in dashboard["metrics"] if r["campaignId"] == "cmp_1" and r["date"] == today]
    assert rows, "expected a live metric row for cmp_1"
    assert rows[0]["telegramSubscribers"] == 2

    assert dashboard["funnelSummary"]["rates"]["telegramStartRate"] > 0


def test_dashboard_join_leaves_rows_at_zero_without_funnel_events(tmp_path):
    today = datetime.now(timezone.utc).date().isoformat()
    dashboard = dashboard_from_knowledge_base(_knowledge(today), funnel_storage_dir=tmp_path / "storage")

    rows = [r for r in dashboard["metrics"] if r["campaignId"] == "cmp_1"]
    assert rows and all(r["telegramSubscribers"] == 0 for r in rows)
    assert dashboard["funnelSummary"]["totalEvents"] == 0

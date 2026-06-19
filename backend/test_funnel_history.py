"""Tests for the per-day funnel history builder — it must aggregate each day with the
app's shared metric extraction and derive VSL daily views from cumulative snapshots."""

from datetime import date

from backend.funnel_history import (
    build_history_series,
    crm_leads_by_date,
    daily_meta_metrics,
    daterange,
    event_users_by_date,
    load_vsl_snapshots,
    record_vsl_snapshot,
)


def _meta_row(day, *, campaign_id, clicks, link_clicks, landing, leads, subscribe=0, spend=0.0):
    return {
        "date_start": day,
        "campaign_id": campaign_id,
        "spend": spend,
        "impressions": clicks * 10,
        "clicks": clicks,
        "actions": [
            {"action_type": "link_click", "value": link_clicks},
            {"action_type": "landing_page_view", "value": landing},
            {"action_type": "lead", "value": leads},
            {"action_type": "subscribe", "value": subscribe},
        ],
    }


META_ROWS = [
    _meta_row("2026-06-17", campaign_id="c1", clicks=100, link_clicks=80, landing=60, leads=40, spend=10.0),
    _meta_row("2026-06-18", campaign_id="c1", clicks=120, link_clicks=90, landing=70, leads=50, spend=12.0),
    _meta_row("2026-06-18", campaign_id="c2", clicks=999, link_clicks=999, landing=999, leads=999, spend=99.0),
]


def test_daily_meta_metrics_groups_by_date_and_scopes_campaign():
    by_date = daily_meta_metrics(META_ROWS, campaign_id="c1")
    assert set(by_date) == {"2026-06-17", "2026-06-18"}
    assert by_date["2026-06-17"]["linkClicks"] == 80
    assert by_date["2026-06-17"]["landingPageViews"] == 60
    assert by_date["2026-06-17"]["leads"] == 40
    assert by_date["2026-06-18"]["leads"] == 50  # c2's 999 excluded by scope
    assert by_date["2026-06-18"]["spend"] == 12.0


def test_daily_meta_metrics_account_wide_sums_all_campaigns():
    by_date = daily_meta_metrics(META_ROWS, campaign_id=None)
    assert by_date["2026-06-18"]["leads"] == 50 + 999


def test_event_users_by_date_dedupes_per_day():
    events = [
        {"eventName": "bot_start", "receivedAt": "2026-06-17T08:00:00Z", "telegramUserId": "A"},
        {"eventName": "bot_start", "receivedAt": "2026-06-17T09:00:00Z", "telegramUserId": "A"},  # repeat
        {"eventName": "bot_start", "receivedAt": "2026-06-17T10:00:00Z", "telegramUserId": "B"},
        {"eventName": "bot_start", "receivedAt": "2026-06-18T10:00:00Z", "telegramUserId": "A"},
        {"eventName": "telegram_link_click", "receivedAt": "2026-06-17T07:00:00Z", "visitorId": "v1"},
    ]
    assert event_users_by_date(events, "bot_start") == {"2026-06-17": 2, "2026-06-18": 1}
    assert event_users_by_date(events, "telegram_link_click") == {"2026-06-17": 1}


def test_crm_leads_by_date_counts_by_created():
    leads = [
        {"createdAt": "2026-06-17T12:00:00+03:00"},
        {"createdAt": "2026-06-17T15:00:00+03:00"},
        {"createdAt": "2026-06-18T09:00:00+03:00"},
        {"createdAt": ""},  # undated -> ignored
    ]
    assert crm_leads_by_date(leads) == {"2026-06-17": 2, "2026-06-18": 1}


def test_daterange_is_inclusive():
    assert daterange(date(2026, 6, 17), date(2026, 6, 19)) == ["2026-06-17", "2026-06-18", "2026-06-19"]


def test_build_history_series_counts_start_rate_and_vsl_delta():
    dates = ["2026-06-17", "2026-06-18"]
    meta_by_date = daily_meta_metrics(META_ROWS, campaign_id="c1")
    points = build_history_series(
        dates=dates,
        meta_by_date=meta_by_date,
        bot_starts_by_date={"2026-06-17": 2, "2026-06-18": 1},
        link_clicks_by_date={"2026-06-17": 4},  # day 2 has no button clicks -> falls back to leads
        crm_by_date={"2026-06-17": 3, "2026-06-18": 2},
        vsl_cumulative_by_date={"2026-06-17": 100, "2026-06-18": 130},
    )
    assert len(points) == 2

    d1 = points[0]
    assert d1["date"] == "2026-06-17"
    assert d1["counts"] == {
        "linkClicks": 80,
        "landingViews": 60,
        "leads": 40,
        "botStarts": 2,
        "telegramLinkClicks": 4,
        "subscribes": 0,
        "crmLeads": 3,
        "vslViews": None,  # first snapshot day -> no prior to diff -> null
    }
    assert d1["startRate"] == 50.0  # 2 starts ÷ 4 button clicks
    assert d1["startDenominatorSource"] == "telegram_link_click"

    d2 = points[1]
    assert d2["counts"]["vslViews"] == 30  # 130 - 100
    assert d2["counts"]["botStarts"] == 1
    assert d2["startRate"] == 2.0  # 1 start ÷ 50 leads (no button clicks that day)
    assert d2["startDenominatorSource"] == "meta_leads"


def test_build_history_series_is_zero_safe_for_empty_days():
    points = build_history_series(
        dates=["2026-06-19"],
        meta_by_date={},
        bot_starts_by_date={},
        link_clicks_by_date={},
        crm_by_date={},
        vsl_cumulative_by_date={},
    )
    assert points[0]["startRate"] == 0.0
    assert points[0]["counts"]["leads"] == 0
    assert points[0]["counts"]["vslViews"] is None


def test_build_history_series_flags_the_current_day_incomplete():
    points = build_history_series(
        dates=["2026-06-17", "2026-06-18"],
        meta_by_date=daily_meta_metrics(META_ROWS, campaign_id="c1"),
        bot_starts_by_date={},
        link_clicks_by_date={},
        crm_by_date={},
        vsl_cumulative_by_date={},
        today="2026-06-18",
    )
    assert points[0]["incomplete"] is False  # 06-17 is a complete day
    assert points[1]["incomplete"] is True  # 06-18 is the in-progress server day


def test_vsl_snapshot_store_keeps_daily_max_and_ignores_wobble(tmp_path):
    record_vsl_snapshot("2026-06-18", 130, storage_dir=tmp_path)
    assert load_vsl_snapshots(storage_dir=tmp_path) == {"2026-06-18": 130.0}
    # A higher reading (a new daily high) is recorded.
    record_vsl_snapshot("2026-06-18", 145, storage_dir=tmp_path)
    assert load_vsl_snapshots(storage_dir=tmp_path) == {"2026-06-18": 145.0}
    # YouTube's downward wobble (145 -> 120) is ignored — the day keeps its peak, so the
    # daily delta can never go negative.
    record_vsl_snapshot("2026-06-18", 120, storage_dir=tmp_path)
    assert load_vsl_snapshots(storage_dir=tmp_path) == {"2026-06-18": 145.0}
    # None (VSL unconfigured) is a no-op.
    record_vsl_snapshot("2026-06-19", None, storage_dir=tmp_path)
    assert "2026-06-19" not in load_vsl_snapshots(storage_dir=tmp_path)

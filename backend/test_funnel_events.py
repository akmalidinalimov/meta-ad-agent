from backend.funnel_events import (
    build_funnel_summary,
    normalize_funnel_event,
    save_funnel_event,
)


def test_normalize_funnel_event_preserves_attribution_fields():
    event = normalize_funnel_event({
        "event_name": "bot_start",
        "visitor_id": "visitor_1",
        "telegram_user_id": "tg_1",
        "segment": "income",
        "vsl_id": "income_vsl_01",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "ad_id": "ad_1",
        "creative_id": "creative_1",
        "fbclid": "fbclid_1",
    })

    assert event["eventName"] == "bot_start"
    assert event["visitorId"] == "visitor_1"
    assert event["telegramUserId"] == "tg_1"
    assert event["segment"] == "income"
    assert event["vslId"] == "income_vsl_01"
    assert event["campaignId"] == "campaign_1"
    assert event["adSetId"] == "adset_1"
    assert event["adId"] == "ad_1"
    assert event["creativeId"] == "creative_1"
    assert event["fbclid"] == "fbclid_1"


def test_save_funnel_event_appends_jsonl_and_summary_counts(tmp_path):
    storage_dir = tmp_path / "storage"
    save_funnel_event({"event_name": "landing_view", "visitor_id": "v1", "segment": "income"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v1", "segment": "income"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "telegram_user_id": "tg1", "segment": "income"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v2", "telegram_user_id": "tg2", "segment": "business"}, storage_dir=storage_dir)

    summary = build_funnel_summary(storage_dir=storage_dir)

    assert summary["totalEvents"] == 4
    assert summary["eventsByName"]["bot_start"] == 2
    assert summary["eventsBySegment"]["income"]["bot_start"] == 1
    assert summary["eventsBySegment"]["business"]["bot_start"] == 1
    assert summary["uniqueVisitors"] == 2
    assert summary["uniqueTelegramUsers"] == 2

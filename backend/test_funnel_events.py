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


def test_normalize_funnel_event_preserves_custom_bot_steps_as_safe_names():
    event = normalize_funnel_event({
        "event_name": "Offer Button Clicked!",
        "visitor_id": "visitor_1",
        "telegram_user_id": "tg_1",
    })

    assert event["eventName"] == "offer_button_clicked"
    assert event["visitorId"] == "visitor_1"


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
    assert summary["rates"]["telegramStartRate"] == 100


def test_funnel_summary_lists_dynamic_event_steps_in_observed_order(tmp_path):
    storage_dir = tmp_path / "storage"
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "watched_first_lesson", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "offer_button_clicked", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v2", "telegram_user_id": "tg2"}, storage_dir=storage_dir)

    summary = build_funnel_summary(storage_dir=storage_dir)

    assert summary["eventsByName"]["watched_first_lesson"] == 1
    assert summary["eventSteps"] == [
        {"eventName": "telegram_link_click", "count": 1, "uniqueVisitors": 1, "rateFromPrevious": None},
        {"eventName": "bot_start", "count": 2, "uniqueVisitors": 2, "rateFromPrevious": 100},
        {"eventName": "watched_first_lesson", "count": 1, "uniqueVisitors": 1, "rateFromPrevious": 50},
        {"eventName": "offer_button_clicked", "count": 1, "uniqueVisitors": 1, "rateFromPrevious": 100},
    ]


def test_funnel_summary_calculates_downstream_rates(tmp_path):
    storage_dir = tmp_path / "storage"
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v2"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "vsl_key_message_sent", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "form_button_click", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)

    summary = build_funnel_summary(storage_dir=storage_dir)

    assert summary["rates"] == {
        "telegramStartRate": 50,
        "keyMessageReachRate": 100,
        "formClickRate": 100,
        "qualifiedLeadRate": 0,
        "fullPaymentRate": 0,
        "crmAttributedLeadRate": 0.0,
    }


def test_funnel_summary_joins_crm_leads_by_visitor_and_stage(tmp_path):
    from backend.crm_store import save_crm_leads

    storage_dir = tmp_path / "storage"
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "form_button_click", "visitor_id": "v1", "telegram_user_id": "tg1"}, storage_dir=storage_dir)
    save_crm_leads(
        [
            {"crm": "bitrix24", "crmLeadId": "101", "visitorId": "v1", "telegramUserId": "tg1", "stage": "NEW"},
            {"crm": "bitrix24", "crmLeadId": "102", "visitorId": "v2", "telegramUserId": "tg2", "stage": "FULL_PAID"},
        ],
        storage_dir=storage_dir,
    )

    summary = build_funnel_summary(storage_dir=storage_dir)

    assert summary["crm"]["totalLeads"] == 2
    assert summary["crm"]["attributedLeads"] == 1
    assert summary["crm"]["stages"]["NEW"] == 1
    assert summary["crm"]["stages"]["FULL_PAID"] == 1
    assert summary["rates"]["crmAttributedLeadRate"] == 100

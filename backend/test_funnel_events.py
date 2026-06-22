from datetime import datetime, timezone

from backend.funnel_events import (
    build_funnel_summary,
    count_bot_starts,
    count_event_users,
    normalize_funnel_event,
    save_funnel_event,
    select_start_rate,
    telegram_starts_by_campaign_date,
)


def test_select_start_rate_prefers_first_party_button_clicks():
    # telegram_link_click present -> denominator is the first-party button clicks,
    # NOT Meta leads, and the rate is bot_starts / link_clicks.
    out = select_start_rate(bot_starts=12, subscribes=0, link_clicks=40, leads=100)
    assert out["denominatorSource"] == "telegram_link_click"
    assert out["denominator"] == 40
    assert out["numeratorSource"] == "telegram_relay"
    assert out["rate"] == 30.0  # 12 / 40


def test_select_start_rate_falls_back_to_leads_without_tracker():
    # No telegram_link_click yet -> fall back to Meta leads, clearly labelled.
    out = select_start_rate(bot_starts=12, subscribes=0, link_clicks=0, leads=20)
    assert out["denominatorSource"] == "meta_leads"
    assert out["rate"] == 60.0  # 12 / 20


def test_select_start_rate_subscribe_numerator_fallback_and_caps():
    # No relay bot starts -> Meta subscribe numerator; ratio over 100 is capped.
    out = select_start_rate(bot_starts=0, subscribes=50, link_clicks=10, leads=0)
    assert out["numeratorSource"] == "meta_subscribe"
    assert out["rate"] == 100.0  # 50/10 -> capped


def test_select_start_rate_zero_denominator_is_safe():
    out = select_start_rate(bot_starts=5, subscribes=0, link_clicks=0, leads=0)
    assert out["rate"] == 0.0 and out["denominatorSource"] == "none"


def test_count_event_users_dedupes_by_identity(tmp_path):
    storage = tmp_path / "storage"
    for ev in [
        {"event_name": "telegram_link_click", "visitor_id": "v_1"},
        {"event_name": "telegram_link_click", "visitor_id": "v_1"},  # repeat -> once
        {"event_name": "telegram_link_click", "visitor_id": "v_2"},
        {"event_name": "bot_start", "telegram_user_id": "tg_1"},
    ]:
        save_funnel_event(ev, storage_dir=storage)
    assert count_event_users("telegram_link_click", storage_dir=storage) == 2
    assert count_bot_starts(storage_dir=storage) == 1


def test_count_event_users_respects_since_and_until_bounds(tmp_path):
    import json

    storage = tmp_path / "storage"
    storage.mkdir()
    rows = [
        {"eventName": "bot_start", "receivedAt": "2026-06-17T10:00:00+00:00", "telegramUserId": "a"},
        {"eventName": "bot_start", "receivedAt": "2026-06-18T10:00:00+00:00", "telegramUserId": "b"},
        {"eventName": "bot_start", "receivedAt": "2026-06-19T10:00:00+00:00", "telegramUserId": "c"},
    ]
    (storage / "funnel_events.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    # A single bounded day [06-18, 06-19) → only b (today/past-day scope can't leak later).
    assert count_bot_starts(since_iso="2026-06-18", until_iso="2026-06-19", storage_dir=storage) == 1
    assert count_bot_starts(since_iso="2026-06-18", storage_dir=storage) == 2  # since only
    assert count_bot_starts(until_iso="2026-06-19", storage_dir=storage) == 2  # before 06-19


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


def test_telegram_starts_by_campaign_date_counts_bot_starts(tmp_path):
    storage_dir = tmp_path / "storage"
    today = datetime.now(timezone.utc).date().isoformat()
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v1", "campaign_id": "cmp_1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v2", "campaign_id": "cmp_1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v3", "campaign_id": "cmp_2"}, storage_dir=storage_dir)
    # Excluded: not a START, and a START with no campaign to attribute to.
    save_funnel_event({"event_name": "telegram_link_click", "visitor_id": "v4", "campaign_id": "cmp_1"}, storage_dir=storage_dir)
    save_funnel_event({"event_name": "bot_start", "visitor_id": "v5"}, storage_dir=storage_dir)

    counts = telegram_starts_by_campaign_date(storage_dir=storage_dir)

    assert counts == {("cmp_1", today): 2, ("cmp_2", today): 1}


def test_telegram_starts_by_campaign_date_empty_when_no_events(tmp_path):
    assert telegram_starts_by_campaign_date(storage_dir=tmp_path / "storage") == {}


def test_assess_bot_start_health_flags_current_stall():
    from backend.funnel_events import assess_bot_start_health
    # Relay healthy early, then the last 2 trafficked hours have clicks but ZERO starts.
    buckets = [
        {"hour": "2026-06-22T10", "clicks": 70, "starts": 58},
        {"hour": "2026-06-22T11", "clicks": 111, "starts": 104},
        {"hour": "2026-06-22T12", "clicks": 102, "starts": 0},
        {"hour": "2026-06-22T13", "clicks": 45, "starts": 0},
    ]
    h = assess_bot_start_health(buckets)
    assert h["stalled"] is True and h["gapHours"] == 2
    assert h["collectedStartRate"] == round((58 + 104) / (70 + 111) * 100, 1)
    assert "relay" in h["message"].lower()


def test_assess_bot_start_health_window_gap_not_currently_stalled():
    # A gap earlier in the day, but recent hours are healthy -> incomplete, not stalled.
    from backend.funnel_events import assess_bot_start_health
    buckets = [
        {"hour": "2026-06-22T02", "clicks": 81, "starts": 0},
        {"hour": "2026-06-22T03", "clicks": 76, "starts": 0},
        {"hour": "2026-06-22T10", "clicks": 70, "starts": 58},
        {"hour": "2026-06-22T11", "clicks": 111, "starts": 104},
    ]
    h = assess_bot_start_health(buckets)
    assert h["stalled"] is False and h["gapHours"] == 2
    assert "incomplete" in h["message"].lower()


def test_assess_bot_start_health_healthy_is_quiet():
    from backend.funnel_events import assess_bot_start_health
    buckets = [
        {"hour": "2026-06-22T12", "clicks": 100, "starts": 88},
        {"hour": "2026-06-22T13", "clicks": 45, "starts": 40},
    ]
    h = assess_bot_start_health(buckets)
    assert h["stalled"] is False and h["gapHours"] == 0 and h["message"] is None


def test_assess_bot_start_health_ignores_trivial_traffic():
    # An hour with only 1-2 clicks and 0 starts is noise, not a gap.
    from backend.funnel_events import assess_bot_start_health
    buckets = [
        {"hour": "2026-06-22T12", "clicks": 100, "starts": 90},
        {"hour": "2026-06-22T13", "clicks": 2, "starts": 0},
    ]
    h = assess_bot_start_health(buckets)
    assert h["gapHours"] == 0 and h["stalled"] is False

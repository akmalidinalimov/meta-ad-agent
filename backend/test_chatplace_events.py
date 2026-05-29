from backend.chatplace_events import normalize_chatplace_event
from backend.funnel_events import build_funnel_summary, save_funnel_event


def test_normalize_chatplace_event_extracts_visitor_id_from_start_command():
    event = normalize_chatplace_event({
        "event_name": "bot_start",
        "message_text": "/start v_mpq9v4kh_ymk10f",
        "username": "buyer_uz",
        "segment": "income",
        "vsl_id": "income_vsl_01",
        "telegram_bot_id": "income_bot",
    })

    assert event["event_name"] == "bot_start"
    assert event["visitor_id"] == "v_mpq9v4kh_ymk10f"
    assert event["telegram_username"] == "buyer_uz"
    assert event["segment"] == "income"
    assert event["vsl_id"] == "income_vsl_01"
    assert event["telegram_bot_id"] == "income_bot"


def test_normalize_chatplace_event_accepts_nested_chatplace_payload():
    event = normalize_chatplace_event({
        "eventName": "vsl_key_message_sent",
        "client": {
            "chatLink": "https://t.me/buyer_uz",
            "username": "buyer_uz",
            "fullName": "Buyer Uz",
        },
        "variables": {
            "visitor_id": "v_abc123",
            "segment": "business",
            "vsl_id": "business_vsl_01",
            "landing_page_id": "business_lp_01",
            "telegram_bot_id": "business_bot",
            "campaign_id": "cmp_1",
            "adset_id": "as_1",
            "ad_id": "ad_1",
            "creative_id": "cr_1",
        },
    })

    assert event == {
        "event_name": "vsl_key_message_sent",
        "visitor_id": "v_abc123",
        "telegram_user_id": "https://t.me/buyer_uz",
        "telegram_username": "buyer_uz",
        "telegram_full_name": "Buyer Uz",
        "segment": "business",
        "vsl_id": "business_vsl_01",
        "landing_page_id": "business_lp_01",
        "telegram_bot_id": "business_bot",
        "campaign_id": "cmp_1",
        "adset_id": "as_1",
        "ad_id": "ad_1",
        "creative_id": "cr_1",
        "source": "chatplace",
    }


def test_normalize_chatplace_event_extracts_visitor_id_from_telegram_link():
    event = normalize_chatplace_event({
        "event_name": "bot_start",
        "start_payload": "https://t.me/example_bot?start=v_link123",
    })

    assert event["visitor_id"] == "v_link123"


def test_chatplace_event_can_be_saved_as_canonical_funnel_event(tmp_path):
    storage_dir = tmp_path / "storage"
    chatplace_event = normalize_chatplace_event({
        "event_name": "bot_start",
        "message_text": "/start v_join123",
        "client": {"id": "tg_123", "username": "buyer_uz"},
        "variables": {"segment": "income", "telegram_bot_id": "income_bot"},
    })

    saved = save_funnel_event(chatplace_event, storage_dir=storage_dir)
    summary = build_funnel_summary(storage_dir=storage_dir)

    assert saved["eventName"] == "bot_start"
    assert saved["visitorId"] == "v_join123"
    assert saved["telegramUserId"] == "tg_123"
    assert saved["telegramUsername"] == "buyer_uz"
    assert summary["eventsByName"]["bot_start"] == 1
    assert summary["uniqueVisitors"] == 1
    assert summary["uniqueTelegramUsers"] == 1

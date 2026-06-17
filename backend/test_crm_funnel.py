from backend.crm_funnel import (
    build_audience_index,
    build_crm_funnel,
    count_bot_starts_by_audience,
    normalize_aud,
    normalize_phone,
    normalize_username,
    resolve_paid_stage_ids,
)


# --- Task 1: normalization helpers -----------------------------------------


def test_normalize_phone_matches_on_trailing_nine_digits():
    assert normalize_phone("+998901234567") == "901234567"
    assert normalize_phone("998 90 123 45 67") == "901234567"
    assert normalize_phone("901234567") == "901234567"
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_normalize_username_strips_at_and_tme_link():
    assert normalize_username("@Buyer_UZ") == "buyer_uz"
    assert normalize_username("https://t.me/buyer_uz") == "buyer_uz"
    assert normalize_username("") == ""


def test_normalize_aud_strips_src_and_vsl_prefixes():
    assert normalize_aud("src_ai") == "ai"
    assert normalize_aud("vsl_business") == "business"
    assert normalize_aud("IT") == "it"
    assert normalize_aud("") == ""


# --- Task 2: audience index + bot-starts-by-audience ------------------------


def _events():
    return [
        {"eventName": "bot_start", "aud": "ai", "phone": "+998901112233", "telegramUsername": "@ai_buyer", "telegramUserId": "tg1"},
        {"eventName": "bot_start", "aud": "src_business", "phone": "998907778899", "telegramUserId": "tg2"},
        {"eventName": "bot_start", "phone": "+998901112233", "telegramUserId": "tg1"},  # later, no aud -> must not erase 'ai'
        {"eventName": "vsl_key_message_sent", "aud": "it", "phone": "+998905556677"},   # non-start still indexable
    ]


def test_build_audience_index_first_seen_audience_wins():
    index = build_audience_index(_events())
    assert index["byPhone"]["901112233"] == "ai"
    assert index["byPhone"]["907778899"] == "business"
    assert index["byUsername"]["ai_buyer"] == "ai"


def test_count_bot_starts_by_audience_dedupes_by_identity():
    counts = count_bot_starts_by_audience(_events())
    assert counts["ai"] == 1          # tg1 counted once despite two starts
    assert counts["business"] == 1
    assert counts["it"] == 0          # 'it' came from a non-bot_start event


# --- Task 3: paid-stage resolution + matrix --------------------------------

STAGES = [
    {"id": "NEW", "name": "Ne obrabotinniy"},
    {"id": "CONTACTED", "name": "Contacted"},
    {"id": "QUALIFIED", "name": "Qualified"},
    {"id": "PAID", "name": "To'lov qilindi"},
]


def test_resolve_paid_stage_ids_prefers_config_over_heuristic():
    assert resolve_paid_stage_ids(STAGES, configured_ids=["QUALIFIED"]) == {"QUALIFIED"}
    assert resolve_paid_stage_ids(STAGES, configured_ids=None) == {"PAID"}  # keyword "to'l"


def test_build_crm_funnel_matrix_joins_by_phone_and_counts_paid():
    records = [
        {"stage": "PAID", "phone": "+998901112233", "telegramUsername": "", "utmContent": ""},   # -> ai (phone)
        {"stage": "NEW", "phone": "", "telegramUsername": "@ai_buyer", "utmContent": ""},          # -> ai (username)
        {"stage": "CONTACTED", "phone": "", "telegramUsername": "", "utmContent": "business"},     # -> business (utm)
        {"stage": "NEW", "phone": "+998000000000", "telegramUsername": "", "utmContent": ""},      # -> unattributed
    ]
    events = [
        {"eventName": "bot_start", "aud": "ai", "phone": "+998901112233", "telegramUsername": "@ai_buyer", "telegramUserId": "tg1"},
    ]
    out = build_crm_funnel(records, stages=STAGES, events=events, paid_status_ids=None, days=30, refreshed_at="T")
    assert out["stages"] == ["NEW", "CONTACTED", "QUALIFIED", "PAID"]
    assert out["paidStageIds"] == ["PAID"]
    assert out["audiences"]["ai"]["PAID"] == 1
    assert out["audiences"]["ai"]["NEW"] == 1
    assert out["audiences"]["ai"]["submits"] == 2
    assert out["audiences"]["ai"]["paid"] == 1
    assert out["audiences"]["ai"]["paidRate"] == 0.5
    assert out["audiences"]["ai"]["botStarts"] == 1
    assert out["audiences"]["business"]["CONTACTED"] == 1
    assert out["audiences"]["unattributed"]["NEW"] == 1
    assert out["matchRate"] == 0.75   # 3 of 4 matched

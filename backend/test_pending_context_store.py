from __future__ import annotations

from backend.pending_context_store import (
    clear_pending,
    get_pending,
    merge_refinement,
    operator_key,
    set_pending,
)


def test_operator_key_variants():
    assert operator_key(telegram_chat_id=12345) == "tg:12345"
    assert operator_key(telegram_chat_id="987") == "tg:987"
    assert operator_key(session_id="abc") == "web:abc"
    # Telegram wins when both are present.
    assert operator_key(telegram_chat_id=1, session_id="abc") == "tg:1"
    # Empty/missing falls back to the shared default.
    assert operator_key() == "web:default"
    assert operator_key(telegram_chat_id="  ", session_id="") == "web:default"


def test_set_get_clear_roundtrip(tmp_path):
    storage_dir = tmp_path / "storage"
    key = operator_key(session_id="op1")

    assert get_pending(key, storage_dir=storage_dir) is None

    saved = set_pending(
        key,
        {"approvalId": "autonomous_campaign_20260605_010203", "budget": 100.0, "audiences": ["AI"]},
        storage_dir=storage_dir,
    )
    assert saved["approvalId"] == "autonomous_campaign_20260605_010203"
    assert saved["budget"] == 100.0
    assert saved["audiences"] == ["AI"]
    assert saved["openQuestions"] == []
    assert saved["createdAt"]

    fetched = get_pending(key, storage_dir=storage_dir)
    assert fetched == saved

    clear_pending(key, storage_dir=storage_dir)
    assert get_pending(key, storage_dir=storage_dir) is None
    # Clearing a missing key is a no-op.
    clear_pending(key, storage_dir=storage_dir)


def test_set_pending_is_isolated_per_operator(tmp_path):
    storage_dir = tmp_path / "storage"
    set_pending(operator_key(session_id="a"), {"approvalId": "x"}, storage_dir=storage_dir)
    set_pending(operator_key(session_id="b"), {"approvalId": "y"}, storage_dir=storage_dir)

    assert get_pending(operator_key(session_id="a"), storage_dir=storage_dir)["approvalId"] == "x"
    assert get_pending(operator_key(session_id="b"), storage_dir=storage_dir)["approvalId"] == "y"


def test_merge_refinement_applies_budget_and_location_overrides():
    pointer = {"approvalId": "x", "budget": 100, "audiences": ["AI"]}
    overrides = merge_refinement(pointer, "make it $50 and target Tashkent only", None)

    assert overrides["budget"] == 50.0
    assert overrides["locations"] == ["Tashkent"]

    merged = {**pointer, **overrides}
    assert merged["budget"] == 50.0
    assert merged["locations"] == ["Tashkent"]


def test_merge_refinement_returns_only_present_signals():
    # A message with no recognizable signal yields no overrides (no clobbering).
    assert merge_refinement({"approvalId": "x"}, "looks good, thanks", None) == {}


def test_merge_refinement_extracts_segments_and_metric():
    overrides = merge_refinement(
        {"approvalId": "x"},
        "segments: business owners, content creators. optimize for qualified lead",
        None,
    )
    assert overrides["audiences"] == ["business owners", "content creators"]
    assert overrides["successMetric"] == "qualified_lead"

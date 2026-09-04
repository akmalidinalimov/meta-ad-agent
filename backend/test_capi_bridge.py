"""Tests for the CAPI token bridge.

The behaviour that matters is narrow but easy to get silently wrong: hash what Meta expects
hashed, never hash fbp/fbc, and refuse to guess a token. Each of those failures produces an
event Meta accepts and cannot use — a 200 that teaches the algorithm nothing.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from backend.capi_bridge import (
    build_capi_event,
    extract_token,
    hash_phone,
    hash_text,
    is_matchable,
    lookup_identity,
    match_keys,
    normalize_phone,
    remember_identity,
    reset_identity_cache,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_identity_cache()
    yield
    reset_identity_cache()


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --------------------------------------------------------------------------- token


def test_extract_token_from_raw_start_command():
    # What Telegram actually delivers to the bot as the first message.
    assert extract_token("/start v_9f2c1ab34de5") == "v_9f2c1ab34de5"


def test_extract_token_from_full_deep_link():
    link = "https://t.me/ai_bilan_daromad_bot?start=v_9f2c1ab34de5"
    assert extract_token(link) == "v_9f2c1ab34de5"


def test_extract_token_returns_none_rather_than_guessing():
    # A wrong token would credit one person's conversion to another person's ad click,
    # so anything without a v_ token must come back empty.
    assert extract_token("/start") is None
    assert extract_token("vsl_ai") is None
    assert extract_token("") is None
    assert extract_token(None) is None


# --------------------------------------------------------------------------- normalization


def test_normalize_phone_strips_to_digits():
    assert normalize_phone("+998 90 123 45 67") == "998901234567"


def test_normalize_phone_adds_country_code_to_bare_local_number():
    # Bitrix stores both "+998901234567" and the 9-digit "901234567" form.
    assert normalize_phone("901234567") == "998901234567"


def test_normalize_phone_leaves_full_number_untouched():
    assert normalize_phone("998901234567") == "998901234567"


def test_hash_text_lowercases_and_trims_before_hashing():
    assert hash_text("  Nozimaxon  ") == sha("nozimaxon")


def test_hash_phone_hashes_the_normalized_form():
    assert hash_phone("+998901234567") == sha("998901234567")


def test_hashers_ignore_empty_values():
    assert hash_text("") is None and hash_text(None) is None
    assert hash_phone("") is None and hash_phone(None) is None


# --------------------------------------------------------------------------- identity store


def test_remember_and_lookup_round_trip(tmp_path):
    stored = remember_identity(
        {"visitor_id": "v_abc123", "fbp": "fb.1.1700.111", "fbc": "fb.1.1700.CLICKID", "user_agent": "UA/1.0"},
        storage_dir=tmp_path,
    )
    assert stored is not None
    found = lookup_identity("v_abc123", storage_dir=tmp_path)
    assert found["fbp"] == "fb.1.1700.111"
    assert found["fbc"] == "fb.1.1700.CLICKID"
    assert found["userAgent"] == "UA/1.0"


def test_remember_identity_skips_payloads_with_no_browser_identifier(tmp_path):
    # A token with nothing attached cannot raise match quality, so it is not worth a row.
    assert remember_identity({"visitor_id": "v_abc123"}, storage_dir=tmp_path) is None
    assert lookup_identity("v_abc123", storage_dir=tmp_path) is None


def test_remember_identity_skips_payloads_with_no_token(tmp_path):
    assert remember_identity({"fbp": "fb.1.1700.111"}, storage_dir=tmp_path) is None


def test_later_visit_refreshes_the_stored_identity(tmp_path):
    remember_identity({"visitor_id": "v_abc123", "fbp": "old"}, storage_dir=tmp_path)
    remember_identity({"visitor_id": "v_abc123", "fbp": "new", "fbc": "fb.1.1.C"}, storage_dir=tmp_path)
    assert lookup_identity("v_abc123", storage_dir=tmp_path)["fbp"] == "new"


def test_identity_survives_a_process_restart(tmp_path):
    remember_identity({"visitor_id": "v_abc123", "fbp": "fb.1.1700.111"}, storage_dir=tmp_path)
    reset_identity_cache()  # simulates a fresh worker reading the file back
    assert lookup_identity("v_abc123", storage_dir=tmp_path)["fbp"] == "fb.1.1700.111"


def test_expired_identities_are_dropped_on_load(tmp_path, monkeypatch):
    path = tmp_path / "capi_identity.jsonl"
    path.write_text(json.dumps({"token": "v_old", "ts": 0, "fbp": "stale"}) + "\n", encoding="utf-8")
    reset_identity_cache()
    # ts=0 is far outside the 7-day window Meta accepts events for.
    assert lookup_identity("v_old", storage_dir=tmp_path) is None


def test_corrupt_lines_do_not_break_the_store(tmp_path):
    path = tmp_path / "capi_identity.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    reset_identity_cache()
    assert lookup_identity("v_abc123", storage_dir=tmp_path) is None
    assert remember_identity({"visitor_id": "v_healthy1", "fbp": "x"}, storage_dir=tmp_path) is not None


def test_token_shorter_than_the_pattern_minimum_is_rejected():
    # Matches VISITOR_ID_PATTERN in chatplace_events, so both readers agree on what a token is.
    assert extract_token("v_ok") is None
    assert extract_token("v_abc") == "v_abc"


# --------------------------------------------------------------------------- event shaping


def test_event_hashes_person_fields_but_never_fbp_or_fbc():
    event = build_capi_event(
        event_name="CRMLead",
        token="v_abc123",
        phone="+998901234567",
        first_name="Nozimaxon",
        identity={"fbp": "fb.1.1700.111", "fbc": "fb.1.1700.CLICKID", "ip": "1.2.3.4", "userAgent": "UA/1.0"},
    )
    ud = event["user_data"]
    assert ud["ph"] == [sha("998901234567")]
    assert ud["fn"] == [sha("nozimaxon")]
    assert ud["external_id"] == [sha("v_abc123")]
    assert ud["country"] == [sha("uz")]
    # Hashing these would silently destroy the match — the whole point of the bridge.
    assert ud["fbp"] == "fb.1.1700.111"
    assert ud["fbc"] == "fb.1.1700.CLICKID"
    assert ud["client_ip_address"] == "1.2.3.4"
    assert ud["client_user_agent"] == "UA/1.0"


def test_event_id_is_stable_so_retries_dedupe():
    args = dict(event_name="CRMLead", token="v_abc123", phone="+998901234567")
    assert build_capi_event(**args)["event_id"] == build_capi_event(**args)["event_id"]
    assert build_capi_event(**args)["event_id"] == "crmlead_v_abc123"


def test_event_without_identity_is_deliverable_but_not_matchable():
    # This is exactly the July failure mode: Meta accepts it, then cannot attribute it.
    event = build_capi_event(event_name="CRMLead", token="v_abc123", phone="+998901234567")
    assert "ph" in event["user_data"]
    assert is_matchable(event) is False


def test_event_with_browser_identity_is_matchable():
    event = build_capi_event(
        event_name="CRMLead", token="v_abc123", phone="+998901234567", identity={"fbp": "fb.1.1.1"}
    )
    assert is_matchable(event) is True
    assert "fbp" in match_keys(event)


def test_event_carries_audience_when_known():
    event = build_capi_event(event_name="CRMLead", token="v_a", phone="1", aud="ai")
    assert event["custom_data"]["aud"] == "ai"


def test_website_source_includes_the_landing_url(monkeypatch):
    monkeypatch.setenv("META_CAPI_ACTION_SOURCE", "website")
    event = build_capi_event(
        event_name="CRMLead",
        token="v_a",
        phone="1",
        identity={"eventSourceUrl": "https://alikhanova.cloud/"},
    )
    assert event["action_source"] == "website"
    assert event["event_source_url"] == "https://alikhanova.cloud/"


def test_missing_phone_still_produces_a_valid_event():
    # request_phone can be declined; the token alone is still worth sending.
    event = build_capi_event(event_name="CRMLead", token="v_a", identity={"fbp": "fb.1.1.1"})
    assert "ph" not in event["user_data"]
    assert is_matchable(event) is True

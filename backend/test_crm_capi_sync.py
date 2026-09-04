"""Tests for the delayed, CRM-verified conversion sync.

The costly failures here are duplicates (Meta double-counts and the optimiser skews) and
silently dropped conversions on a Meta error. Both are covered.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.capi_bridge import link_phone, remember_identity, reset_identity_cache
from backend.crm_capi_sync import (
    PURCHASE_EVENT,
    QUALIFIED_EVENT,
    build_event_for,
    classify_stage,
    load_sent,
    run_crm_capi_sync,
    save_sent,
    select_pending,
)
from backend.meta_client import MetaApiError

PAID = {"CONVERTED"}
JUNK = {"JUNK"}


@pytest.fixture(autouse=True)
def _clean():
    reset_identity_cache()
    yield
    reset_identity_cache()


def lead(lead_id, stage, phone="+998901234567", **extra):
    return {"crmLeadId": str(lead_id), "stage": stage, "phone": phone, "title": "AI Creators", **extra}


# --------------------------------------------------------------------------- classification


def test_paid_and_junk_are_recognised():
    assert classify_stage("CONVERTED", paid_ids=PAID, junk_ids=JUNK) == "paid"
    assert classify_stage("JUNK", paid_ids=PAID, junk_ids=JUNK) == "junk"


def test_anything_not_junk_counts_as_qualified_by_default():
    # Permissive on purpose: a missing conversion costs Meta more learning than a loose
    # definition does. These are the real status ids seen in the account.
    for stage in ("PROCESSED", "UC_VUJHS2", "UC_8Y6Y8I", "IN_PROCESS", "UC_3Y9MU5"):
        assert classify_stage(stage, paid_ids=PAID, junk_ids=JUNK) == "qualified"


def test_explicit_qualified_list_tightens_the_rule():
    tight = {"PROCESSED"}
    assert classify_stage("PROCESSED", paid_ids=PAID, junk_ids=JUNK, qualified_ids=tight) == "qualified"
    assert classify_stage("UC_VUJHS2", paid_ids=PAID, junk_ids=JUNK, qualified_ids=tight) == "unknown"


def test_blank_stage_is_never_sent():
    assert classify_stage("", paid_ids=PAID, junk_ids=JUNK) == "unknown"


# --------------------------------------------------------------------------- selection


def test_junk_leads_are_never_sent():
    assert select_pending([lead(1, "JUNK")], {}, paid_ids=PAID, junk_ids=JUNK) == []


def test_qualified_lead_is_selected_once():
    pending = select_pending([lead(1, "PROCESSED")], {}, paid_ids=PAID, junk_ids=JUNK)
    assert [name for _, name in pending] == [QUALIFIED_EVENT]


def test_already_sent_is_not_resent():
    sent = {"1": [QUALIFIED_EVENT]}
    assert select_pending([lead(1, "PROCESSED")], sent, paid_ids=PAID, junk_ids=JUNK) == []


def test_paid_lead_backfills_the_qualified_event_it_never_got():
    # A lead can go straight to paid without passing through a worked status.
    pending = select_pending([lead(1, "CONVERTED")], {}, paid_ids=PAID, junk_ids=JUNK)
    assert [name for _, name in pending] == [QUALIFIED_EVENT, PURCHASE_EVENT]


def test_paid_lead_that_already_qualified_only_sends_the_purchase():
    sent = {"1": [QUALIFIED_EVENT]}
    pending = select_pending([lead(1, "CONVERTED")], sent, paid_ids=PAID, junk_ids=JUNK)
    assert [name for _, name in pending] == [PURCHASE_EVENT]


def test_lead_without_an_id_is_skipped():
    assert select_pending([{"stage": "PROCESSED"}], {}, paid_ids=PAID, junk_ids=JUNK) == []


# --------------------------------------------------------------------------- event building


def test_delayed_event_recovers_the_browser_identity_from_the_phone(tmp_path):
    # The whole point: at capture we stored token -> fbp/fbc and linked the phone. Weeks
    # later the CRM knows only the phone, and the event still goes out matched.
    remember_identity(
        {"visitor_id": "v_abc123", "fbp": "fb.1.1700.111", "fbc": "fb.1.1700.CLICK"}, storage_dir=tmp_path
    )
    link_phone("+998901234567", "v_abc123", storage_dir=tmp_path)

    event = build_event_for(lead(1, "PROCESSED"), QUALIFIED_EVENT, storage_dir=tmp_path)
    assert event["user_data"]["fbp"] == "fb.1.1700.111"
    assert event["user_data"]["fbc"] == "fb.1.1700.CLICK"
    assert event["event_name"] == QUALIFIED_EVENT


def test_event_without_a_stored_identity_still_goes_out_unmatched(tmp_path):
    event = build_event_for(lead(1, "PROCESSED"), QUALIFIED_EVENT, storage_dir=tmp_path)
    assert "ph" in event["user_data"]
    assert "fbp" not in event["user_data"]


def test_purchase_carries_value_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("META_CAPI_PURCHASE_VALUE", "400")
    monkeypatch.setenv("META_CAPI_CURRENCY", "USD")
    event = build_event_for(lead(1, "CONVERTED"), PURCHASE_EVENT, storage_dir=tmp_path)
    assert event["custom_data"]["value"] == "400"
    assert event["custom_data"]["currency"] == "USD"


# --------------------------------------------------------------------------- orchestration


def test_dry_run_sends_nothing_but_reports_what_would_go(tmp_path):
    result = asyncio.run(run_crm_capi_sync(
        [lead(1, "PROCESSED"), lead(2, "JUNK")],
        paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, dry_run=True,
    ))
    assert result["pending"] == 1 and result["sent"] == 0
    assert load_sent(storage_dir=tmp_path) == {}


def test_successful_run_records_what_was_sent(tmp_path):
    async def sender(config, events, **kwargs):
        return {"events_received": len(events)}

    result = asyncio.run(run_crm_capi_sync(
        [lead(1, "PROCESSED"), lead(2, "CONVERTED")],
        paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, sender=sender,
    ))
    assert result["sent"] == 3  # lead 1 qualified; lead 2 qualified + purchase
    assert sorted(load_sent(storage_dir=tmp_path)["2"]) == [PURCHASE_EVENT, QUALIFIED_EVENT]


def test_rerunning_sends_nothing_twice(tmp_path):
    calls = []

    async def sender(config, events, **kwargs):
        calls.append(len(events))
        return {"events_received": len(events)}

    leads = [lead(1, "PROCESSED")]
    asyncio.run(run_crm_capi_sync(leads, paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, sender=sender))
    second = asyncio.run(run_crm_capi_sync(leads, paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, sender=sender))
    assert calls == [1]  # not called again
    assert second["pending"] == 0


def test_meta_error_leaves_the_conversions_unmarked_so_they_retry(tmp_path):
    async def boom(config, events, **kwargs):
        raise MetaApiError("rate limited")

    result = asyncio.run(run_crm_capi_sync(
        [lead(1, "PROCESSED")], paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, sender=boom
    ))
    assert "rate limited" in result["error"]
    # Nothing recorded as sent -> the next run retries instead of silently losing it.
    assert load_sent(storage_dir=tmp_path) == {}


def test_matched_and_unmatched_are_reported_separately(tmp_path):
    remember_identity({"visitor_id": "v_abc123", "fbp": "fb.1.1.1"}, storage_dir=tmp_path)
    link_phone("+998901111111", "v_abc123", storage_dir=tmp_path)

    async def sender(config, events, **kwargs):
        return {"events_received": len(events)}

    result = asyncio.run(run_crm_capi_sync(
        [lead(1, "PROCESSED", phone="+998901111111"), lead(2, "PROCESSED", phone="+998902222222")],
        paid_ids=PAID, junk_ids=JUNK, storage_dir=tmp_path, sender=sender,
    ))
    # The split is the health metric: unmatched conversions mean the token bridge is leaking.
    assert result["matched"] == 1
    assert result["unmatched"] == 1


def test_corrupt_sent_state_does_not_block_the_run(tmp_path):
    (tmp_path / "capi_sent.json").write_text("{ broken", encoding="utf-8")
    assert load_sent(storage_dir=tmp_path) == {}
    save_sent({"1": [QUALIFIED_EVENT]}, storage_dir=tmp_path)
    assert load_sent(storage_dir=tmp_path) == {"1": [QUALIFIED_EVENT]}

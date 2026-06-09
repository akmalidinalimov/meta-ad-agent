import asyncio
from datetime import datetime, timezone

import pytest

import backend.meta_live as meta_live
from backend.meta_client import MetaApiError, MetaConfig


NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _configured() -> MetaConfig:
    return MetaConfig(
        access_token="tok",
        app_id="app",
        ad_account_id="act_123",
        business_id="biz",
        api_version="v23.0",
        pixel_id="",
    )


def _unconfigured() -> MetaConfig:
    return MetaConfig(
        access_token="",
        app_id="",
        ad_account_id="",
        business_id="",
        api_version="v23.0",
        pixel_id="",
    )


# --- is_status_active truth table ---------------------------------------------

def test_active_no_stop_is_active():
    assert meta_live.is_status_active({"effective_status": "ACTIVE"}, now=NOW) is True


def test_active_with_past_stop_is_inactive():
    entity = {"effective_status": "ACTIVE", "stop_time": "2026-01-01T00:00:00+0000"}
    assert meta_live.is_status_active(entity, now=NOW) is False


def test_active_with_future_stop_is_active():
    entity = {"effective_status": "ACTIVE", "stop_time": "2027-01-01T00:00:00+0000"}
    assert meta_live.is_status_active(entity, now=NOW) is True


def test_paused_is_inactive():
    assert meta_live.is_status_active({"effective_status": "PAUSED"}, now=NOW) is False


def test_bad_timestamp_falls_back_to_status():
    entity = {"status": "ACTIVE", "end_time": "not-a-date"}
    assert meta_live.is_status_active(entity, now=NOW) is True


def test_adset_uses_end_time():
    entity = {"effective_status": "ACTIVE", "end_time": "2026-01-01T00:00:00+0000"}
    assert meta_live.is_status_active(entity, now=NOW) is False


# --- filter helpers -----------------------------------------------------------

def test_active_filters_by_parent_id():
    acct = meta_live.LiveAccount(
        campaigns=[
            {"id": "1", "effective_status": "ACTIVE"},
            {"id": "2", "effective_status": "PAUSED"},
        ],
        adsets=[
            {"id": "a", "campaign_id": "1", "effective_status": "ACTIVE"},
            {"id": "b", "campaign_id": "2", "effective_status": "ACTIVE"},
        ],
        ads=[{"id": "x", "adset_id": "a", "effective_status": "ACTIVE"}],
        source="live",
        fetched_at="now",
    )
    assert [c["id"] for c in meta_live.active_campaigns(acct, now=NOW)] == ["1"]
    assert [a["id"] for a in meta_live.active_adsets(acct, campaign_id="1", now=NOW)] == ["a"]
    assert [a["id"] for a in meta_live.active_ads(acct, adset_id="a", now=NOW)] == ["x"]


# --- TTL cache + fetch --------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache():
    meta_live._cache.clear()
    yield
    meta_live._cache.clear()


def _patch_fetchers(monkeypatch, calls):
    async def fake_campaigns(config):
        calls["n"] += 1
        return [{"id": "1", "name": "Live", "effective_status": "ACTIVE"}]

    async def fake_adsets(config):
        return []

    async def fake_ads(config):
        return []

    monkeypatch.setattr(meta_live, "get_campaigns", fake_campaigns)
    monkeypatch.setattr(meta_live, "get_ad_sets", fake_adsets)
    monkeypatch.setattr(meta_live, "get_ads", fake_ads)


def test_live_fetch_and_ttl_cache(monkeypatch):
    monkeypatch.setattr(meta_live, "get_meta_config", _configured)
    calls = {"n": 0}
    _patch_fetchers(monkeypatch, calls)

    clock = {"t": 1000.0}
    monkeypatch.setattr(meta_live.time, "monotonic", lambda: clock["t"])

    first = asyncio.run(meta_live.get_live_account())
    assert first.is_live and first.campaigns[0]["name"] == "Live"
    assert calls["n"] == 1

    # Within TTL: cache hit, no new fetch.
    clock["t"] = 1030.0
    second = asyncio.run(meta_live.get_live_account())
    assert calls["n"] == 1
    assert second is first

    # Past TTL: cache miss, re-fetch.
    clock["t"] = 1100.0
    asyncio.run(meta_live.get_live_account())
    assert calls["n"] == 2


def test_snapshot_fallback_when_not_configured(monkeypatch):
    monkeypatch.setattr(meta_live, "get_meta_config", _unconfigured)
    knowledge = {"raw": {"campaigns": [{"id": "9", "name": "Cached"}]}}

    acct = asyncio.run(meta_live.get_live_account(knowledge=knowledge))
    assert acct.source == "snapshot"
    assert acct.is_live is False
    assert acct.error == "Meta not connected"
    assert acct.campaigns[0]["name"] == "Cached"


def test_snapshot_fallback_on_api_error(monkeypatch):
    monkeypatch.setattr(meta_live, "get_meta_config", _configured)

    async def boom(config):
        raise MetaApiError("rate limited")

    monkeypatch.setattr(meta_live, "get_campaigns", boom)
    monkeypatch.setattr(meta_live, "get_ad_sets", boom)
    monkeypatch.setattr(meta_live, "get_ads", boom)

    knowledge = {"raw": {"campaigns": [{"id": "9", "name": "Cached"}]}}
    acct = asyncio.run(meta_live.get_live_account(knowledge=knowledge))
    assert acct.source == "snapshot"
    assert acct.error == "rate limited"
    assert acct.campaigns[0]["name"] == "Cached"

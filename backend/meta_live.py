"""Live Meta account snapshot with a short TTL cache and snapshot fallback.

Chat answers about "what campaigns are active?" must reflect the LIVE Meta state,
not the cached `storage/meta_knowledge_base.json` snapshot (which can hold expired
campaigns). This module fetches campaigns/ad sets/ads live, caches them briefly,
and falls back to the saved knowledge base when Meta is unreachable or unconfigured.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .meta_client import (
    MetaApiError,
    get_ad_sets,
    get_ads,
    get_campaigns,
    get_meta_config,
)

# Meta returns timestamps like "2026-04-26T10:00:00+0000".
_META_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# Short TTL so repeated chat turns within one operator session do not re-hit the
# Meta API, while still staying fresh enough to reflect live status changes.
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, "LiveAccount"]] = {}


@dataclass
class LiveAccount:
    campaigns: list[dict]
    adsets: list[dict]
    ads: list[dict]
    source: str  # "live" | "snapshot"
    fetched_at: str
    error: str | None = None

    @property
    def is_live(self) -> bool:
        return self.source == "live"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_snapshot(knowledge: dict | None, *, error: str | None) -> LiveAccount:
    raw = (knowledge or {}).get("raw", {}) if isinstance(knowledge, dict) else {}
    return LiveAccount(
        campaigns=list(raw.get("campaigns", []) or []),
        adsets=list(raw.get("adsets", []) or []),
        ads=list(raw.get("ads", []) or []),
        source="snapshot",
        fetched_at=_now_iso(),
        error=error,
    )


async def get_live_account(*, knowledge: dict | None = None, force: bool = False) -> LiveAccount:
    """Return the live Meta account snapshot, falling back to the saved knowledge base.

    On a cache hit within the TTL the cached live result is returned. On any failure
    (Meta not configured, API error, unexpected exception) we degrade gracefully to the
    stored snapshot so chat still answers — flagged via ``source == "snapshot"``.
    """
    config = get_meta_config()
    if not config.is_configured:
        return _from_snapshot(knowledge, error="Meta not connected")

    account_key = config.ad_account_id
    if not force:
        cached = _cache.get(account_key)
        if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    try:
        campaigns, adsets, ads = await asyncio.gather(
            get_campaigns(config),
            get_ad_sets(config),
            get_ads(config),
        )
    except MetaApiError as error:
        return _from_snapshot(knowledge, error=str(error))
    except Exception as error:  # noqa: BLE001 - never let a live fetch break chat
        return _from_snapshot(knowledge, error=str(error))

    account = LiveAccount(
        campaigns=list(campaigns or []),
        adsets=list(adsets or []),
        ads=list(ads or []),
        source="live",
        fetched_at=_now_iso(),
        error=None,
    )
    _cache[account_key] = (time.monotonic(), account)
    return account


def _stop_field(entity: dict[str, Any]) -> str | None:
    """Pick the relevant end timestamp: campaigns use stop_time, adsets/ads use end_time."""
    value = entity.get("stop_time") or entity.get("end_time")
    return str(value) if value else None


def is_status_active(entity: dict[str, Any], *, now: datetime | None = None) -> bool:
    """True iff the entity is ACTIVE and its stop/end time is absent or in the future.

    Status comes from effective_status (falling back to status). If the stop timestamp
    fails to parse we fall back to status-only, since a malformed value should not hide
    a genuinely active entity.
    """
    status = str(entity.get("effective_status") or entity.get("status") or "").upper()
    if status != "ACTIVE":
        return False

    stop = _stop_field(entity)
    if not stop:
        return True

    try:
        stop_dt = datetime.strptime(stop, _META_TIME_FORMAT)
    except (ValueError, TypeError):
        return True  # status-only fallback on unparseable timestamps

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return stop_dt > current


def active_campaigns(acct: LiveAccount, *, now: datetime | None = None) -> list[dict]:
    return [c for c in acct.campaigns if isinstance(c, dict) and is_status_active(c, now=now)]


def active_adsets(acct: LiveAccount, campaign_id: str | None = None, *, now: datetime | None = None) -> list[dict]:
    return [
        a
        for a in acct.adsets
        if isinstance(a, dict)
        and is_status_active(a, now=now)
        and (campaign_id is None or str(a.get("campaign_id") or "") == str(campaign_id))
    ]


def active_ads(acct: LiveAccount, adset_id: str | None = None, *, now: datetime | None = None) -> list[dict]:
    return [
        a
        for a in acct.ads
        if isinstance(a, dict)
        and is_status_active(a, now=now)
        and (adset_id is None or str(a.get("adset_id") or "") == str(adset_id))
    ]

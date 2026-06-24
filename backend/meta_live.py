"""Live Meta account snapshot with a short TTL cache and snapshot fallback.

Chat answers about "what campaigns are active?" must reflect the LIVE Meta state,
not the cached `storage/meta_knowledge_base.json` snapshot (which can hold expired
campaigns). This module fetches campaigns/ad sets/ads live, caches them briefly,
and falls back to the saved knowledge base when Meta is unreachable or unconfigured.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .meta_client import (
    MetaApiError,
    get_ad_sets,
    get_ads,
    get_adstudies,
    get_campaigns,
    get_meta_config,
    get_saved_audiences,
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
    # Optional introspection data. Default [] so existing positional/keyword
    # constructions (and snapshot fallback) keep working when these are absent.
    adstudies: list[dict] = field(default_factory=list)
    saved_audiences: list[dict] = field(default_factory=list)

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
        adstudies=[],
        saved_audiences=[],
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

    async def _safe(coro) -> list[dict]:
        """Run an OPTIONAL fetch; a missing scope / no-data account must not blank the
        core campaigns/adsets/ads or trigger the whole-account snapshot fallback."""
        try:
            return list(await coro or [])
        except Exception:  # noqa: BLE001 - optional data only; degrade to []
            return []

    try:
        campaigns, adsets, ads, adstudies, saved_audiences = await asyncio.gather(
            get_campaigns(config),
            get_ad_sets(config),
            get_ads(config),
            _safe(get_adstudies(config)),
            _safe(get_saved_audiences(config)),
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
        adstudies=list(adstudies or []),
        saved_audiences=list(saved_audiences or []),
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


def campaign_adsets(acct: LiveAccount, campaign_id: str, *, now: datetime | None = None) -> list[dict]:
    """ALL ad sets for a campaign (active or not), matched by str(campaign_id)."""
    return [
        a
        for a in acct.adsets
        if isinstance(a, dict) and str(a.get("campaign_id") or "") == str(campaign_id)
    ]


def custom_audience_names(acct: LiveAccount) -> dict[str, str]:
    """{str(id): name} for the account's saved/custom audiences."""
    names: dict[str, str] = {}
    for audience in acct.saved_audiences:
        if not isinstance(audience, dict):
            continue
        aud_id = audience.get("id")
        if aud_id is None:
            continue
        names[str(aud_id)] = str(audience.get("name") or "")
    return names


def ab_test_for_campaign(acct: LiveAccount, campaign_id: str) -> dict | None:
    """Return the adstudy whose cells reference this campaign, else None.

    A cell's adsets may carry the campaign_id directly, or only the adset id — in
    which case we match against the campaign's own ad set ids from acct.adsets.
    """
    target = str(campaign_id)
    campaign_adset_ids = {
        str(a.get("id"))
        for a in acct.adsets
        if isinstance(a, dict) and str(a.get("campaign_id") or "") == target and a.get("id") is not None
    }

    for study in acct.adstudies:
        if not isinstance(study, dict):
            continue
        cells = (study.get("cells") or {})
        cell_rows = cells.get("data", cells) if isinstance(cells, dict) else cells
        for cell in cell_rows or []:
            if not isinstance(cell, dict):
                continue
            cell_adsets = (cell.get("adsets") or {})
            adset_rows = cell_adsets.get("data", cell_adsets) if isinstance(cell_adsets, dict) else cell_adsets
            for adset in adset_rows or []:
                if not isinstance(adset, dict):
                    continue
                if str(adset.get("campaign_id") or "") == target:
                    return study
                if str(adset.get("id") or "") in campaign_adset_ids:
                    return study
    return None

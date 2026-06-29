"""Live campaign list + live per-campaign KPI bundle for the dashboard.

These read LIVE Meta data on demand (NOT the synced knowledge-base snapshot), so a
just-created / just-running campaign shows up immediately and selecting it returns
fresh KPIs + funnel rates. Both routes sit behind the dashboard session guard (they
are deliberately NOT in app._AUTH_PUBLIC_PATHS).

- GET /api/campaigns/live   — live campaigns (fetched fresh each call), optionally
  limited to those CREATED in the last N days. `force` is accepted (the Refresh button
  sends it) but the list is always fetched live, so it is effectively a no-op.
- GET /api/campaigns/kpis   — live KPI bundle (spend/leads/CPL/CTR + Visit/Lead/START
  rates) for one campaign, or the whole account when campaignId is omitted/"all".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from ..analysis_engine import conversion_label, count_conversion, summarize_overall, valid_rows
from ..funnel_events import (
    bot_start_health,
    count_bot_starts,
    count_event_users,
    select_start_rate,
    telegram_starts_by_campaign_date,
)
from ..meta_client import MetaApiError, get_ad_sets, get_entity_insights, get_insights, get_meta_config
from ..meta_sync import normalize_sync_days

router = APIRouter()


def _parse_meta_time(value: Any) -> datetime | None:
    """Parse Meta timestamps like '2026-06-16T08:39:28+0000' to an aware datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _map_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    daily = _as_float(campaign.get("daily_budget"))  # Meta reports budget in minor units
    return {
        "id": str(campaign.get("id") or ""),
        "name": campaign.get("name") or "",
        "status": campaign.get("status"),
        "effectiveStatus": campaign.get("effective_status"),
        "objective": campaign.get("objective"),
        "dailyBudgetUsd": round(daily / 100, 2) if daily else None,
        "createdAt": campaign.get("created_time"),
        "startedAt": campaign.get("start_time"),
        "stoppedAt": campaign.get("stop_time"),
    }


@router.get("/api/campaigns/live")
async def campaigns_live(createdWithinDays: int | None = None, force: bool = False) -> dict[str, Any]:
    """Live campaigns from Meta. Fetches the campaign list DIRECTLY via get_campaigns so
    the picker never depends on the heavier ad-set/ad fetch (and a just-created campaign
    always appears) — it degrades to the saved snapshot's campaigns ONLY if the live
    campaign call itself fails. When ``createdWithinDays`` is set, only campaigns CREATED
    within that window are returned (unknown created dates are excluded so the filter
    can't leak old ones). Newest-created first. ``force`` is accepted for API symmetry
    with the dashboard Refresh; the campaign list is always fetched fresh."""
    from ..knowledge_base import load_knowledge_base
    from ..meta_client import MetaApiError, get_campaigns

    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta is not connected.", "campaigns": []}

    source = "live"
    try:
        raw_campaigns = await get_campaigns(config)
    except MetaApiError:
        raw_campaigns = ((load_knowledge_base() or {}).get("raw") or {}).get("campaigns", []) or []
        source = "snapshot"

    campaigns = [_map_campaign(c) for c in raw_campaigns if isinstance(c, dict) and c.get("id")]

    if createdWithinDays and createdWithinDays > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=createdWithinDays)
        campaigns = [
            c for c in campaigns
            if (parsed := _parse_meta_time(c.get("createdAt"))) is not None and parsed >= cutoff
        ]

    campaigns.sort(key=lambda c: str(c.get("createdAt") or ""), reverse=True)
    return {
        "ok": True,
        "source": source,  # "live", or "snapshot" only if the live campaign call failed
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "createdWithinDays": createdWithinDays,
        "campaigns": campaigns,
    }


def _parse_day(value: str | None) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# {campaign_id -> conversion event} from ad sets' promoted_object, cached so the dashboard's
# per-campaign conversion stage is computed against the campaign's OWN optimized event.
_EVENT_MAP_CACHE: dict[str, Any] = {"at": None, "map": {}}


async def _campaign_event_map(config: Any) -> dict[str, str]:
    """{campaign_id -> conversion event} from each ad set's promoted_object.custom_event_type
    (or 'CUSTOM:<id>' for a custom conversion); the most common event per campaign wins.
    Cached 120s; on a fetch failure returns the last good map so the conversion stage
    degrades to the generic lead+registration definition rather than erroring."""
    now = datetime.now(timezone.utc)
    cached_at = _EVENT_MAP_CACHE["at"]
    if cached_at and (now - cached_at).total_seconds() < 120:
        return _EVENT_MAP_CACHE["map"]
    try:
        adsets = await get_ad_sets(config)
    except MetaApiError:
        return _EVENT_MAP_CACHE["map"]
    by_campaign: dict[str, Counter] = defaultdict(Counter)
    for adset in adsets:
        cid = str(adset.get("campaign_id") or "")
        promoted = adset.get("promoted_object") or {}
        event = promoted.get("custom_event_type")
        if not event and promoted.get("custom_conversion_id"):
            event = f"CUSTOM:{promoted.get('custom_conversion_id')}"
        if cid and event:
            by_campaign[cid][str(event)] += 1
    event_map = {cid: counter.most_common(1)[0][0] for cid, counter in by_campaign.items() if counter}
    _EVENT_MAP_CACHE.update({"at": now, "map": event_map})
    return event_map


@router.get("/api/campaigns/kpis")
async def campaign_kpis(
    campaignId: str | None = None,
    days: int = 30,
    since: str | None = None,
    until: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Live KPI bundle for one campaign (or the whole account when campaignId is omitted
    or "all"). Reuses analysis_engine.summarize_overall, so every rate matches the rest of
    the app and is capped at 100%. The window is the last ``days`` days, or an explicit
    ``since``..``until`` (YYYY-MM-DD) range (e.g. today only). ``force`` is accepted for API
    symmetry with /live; insights are always fetched fresh (uncached)."""
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta is not connected. Add META_ACCESS_TOKEN + META_AD_ACCOUNT_ID."}

    # Resolve the window: an explicit since..until wins; else the last N days.
    end_day = _parse_day(until) or date.today()
    start_param = _parse_day(since)
    if start_param and start_param <= end_day:
        days = normalize_sync_days((end_day - start_param).days + 1)
    else:
        days = normalize_sync_days(days)
    start_day = end_day - timedelta(days=days - 1)

    scoped = bool(campaignId) and campaignId != "all"
    s_iso, u_iso = start_day.isoformat(), end_day.isoformat()
    # COMPLETE per-campaign data: a selected campaign is fetched via its OWN insights
    # endpoint (get_entity_insights), and "all" is fetched at CAMPAIGN level — both avoid the
    # account-wide ad-daily page cap that was dropping smaller/newer campaigns (so switching
    # to them used to show zeros / mixed values). Aggregated (time_increment=None) since the
    # cards sum the window.
    sync_errors: list[str] = []
    try:
        if scoped:
            raw = await get_entity_insights(config, str(campaignId), since=s_iso, until=u_iso, time_increment=None)
        else:
            raw = await get_insights(config, level="campaign", since=s_iso, until=u_iso, time_increment=None)
        rows = valid_rows(raw)
    except MetaApiError as exc:
        rows = []
        sync_errors = [str(exc)]

    totals = summarize_overall(rows)
    name = next((str(row.get("campaign_name")) for row in rows if row.get("campaign_name")), "") if scoped else ""

    spend = totals.get("spend", 0) or 0
    subscribes = totals.get("subscribes", 0) or 0
    generic_leads = totals.get("leads", 0) or 0  # generic lead+registration (START-rate fallback denom)

    # UNIVERSAL conversion stage: count each campaign's OWN optimized event (from its ad
    # sets' promoted_object), so a "registration"/"view" campaign isn't measured by the
    # `lead` action (which is 0 for it). Scoped → that campaign's event; "all" → each row
    # counted by its own campaign's event. Falls back to generic lead+registration when the
    # event is unknown.
    event_map = await _campaign_event_map(config)
    conversion_event = event_map.get(str(campaignId), "") if scoped else ""
    if scoped:
        leads = int(round(sum(count_conversion(row, conversion_event) for row in rows)))
    else:
        leads = int(round(sum(count_conversion(row, event_map.get(str(row.get("campaign_id")), "")) for row in rows)))
    conv_label = "Conversion rate" if not scoped else conversion_label(conversion_event)

    # Conversion-derived economics (override the generic lead numbers with the campaign's
    # own conversion so CPL / lead-rate reflect what Meta is actually optimizing for).
    landing_views = totals.get("landingPageViews", 0) or 0
    clicks_total = totals.get("clicks", 0) or 0
    conv_cpl = round(spend / leads, 2) if leads else 0.0
    conv_lead_rate = min(100.0, round(leads / landing_views * 100, 1)) if landing_views else 0.0
    conv_lead_rate_from_click = round(leads / clicks_total * 100, 2) if clicks_total else 0.0

    # START rate from FIRST-PARTY Telegram bot-starts (funnel_events), NOT Meta's
    # `subscribe` action: a lead-optimized account reports 0 subscribes even while real
    # bot-starts flow, so subscribes/leads would always read 0%. bot_start events are not
    # yet tagged with a campaign_id, so they can only be attributed ACCOUNT-WIDE — when a
    # specific campaign is selected we use its attributed starts if any exist, else fall
    # back to the account-wide count (startScope tells the UI which). select_start_rate
    # prefers the first-party relay over Meta subscribe and the first-party click
    # denominator over Meta leads, capped at 100%. The window is bounded [start_day, end_day]
    # so a single-day ("today") scope doesn't leak later starts.
    since_iso = start_day.isoformat()
    until_iso = (end_day + timedelta(days=1)).isoformat()
    account_starts = count_bot_starts(since_iso=since_iso, until_iso=until_iso)
    link_clicks = count_event_users("telegram_link_click", since_iso=since_iso, until_iso=until_iso)
    # First-party "filled the form inside the bot" signal (a ChatPlace relay fires
    # crm_form_submit, like bot_start). This is the CORRECT CRM-fill numerator — the bot's
    # in-chat form — not the Bitrix "Cell B" tag (which is the no-bot direct landing form).
    form_submits = count_event_users("crm_form_submit", since_iso=since_iso, until_iso=until_iso)
    # First-party "started watching the VSL inside the bot" signal (a ChatPlace relay fires
    # vsl_sequence_started, like bot_start). This is the CORRECT VSL-view numerator — a YouTube
    # view-count can't see in-bot watching. vsl_key_message_sent = a later checkpoint = watch-depth.
    # Both are 0 until the ChatPlace relay exists, so the card shows "not connected" until then.
    vsl_plays = count_event_users("vsl_sequence_started", since_iso=since_iso, until_iso=until_iso)
    vsl_key_message = count_event_users("vsl_key_message_sent", since_iso=since_iso, until_iso=until_iso)
    bot_starts, start_scope = account_starts, "account"
    if scoped:
        since_date, end_date = start_day.isoformat(), end_day.isoformat()
        campaign_starts = sum(
            count
            for (cid, day), count in telegram_starts_by_campaign_date().items()
            if str(cid) == str(campaignId) and since_date <= day <= end_date
        )
        if campaign_starts:
            bot_starts, start_scope = campaign_starts, "campaign"
    # START-rate fallback denominator stays the generic Meta lead (people who could start
    # the bot), independent of which conversion the campaign optimizes for.
    start = select_start_rate(bot_starts=bot_starts, subscribes=subscribes, link_clicks=link_clicks, leads=generic_leads)
    # Data-health guard: flag when the START rate is starved by a bot_start collection gap
    # (clicks flowing but the ChatPlace relay logged no starts) so the UI can warn "data
    # incomplete" instead of showing a misleadingly low number as if it were real.
    start_health = bot_start_health(since_iso=since_iso, until_iso=until_iso)

    return {
        "ok": True,
        "source": "live",
        "days": days,
        "since": start_day.isoformat(),
        "until": end_day.isoformat(),
        "campaignId": str(campaignId) if scoped else "all",
        "campaignName": name,
        "hasData": bool(rows),
        # The campaign's optimized conversion event + a friendly card label, so the UI shows
        # "Registration rate" / "View rate" instead of a misleading "Lead rate".
        "conversionEvent": conversion_event,
        "conversionLabel": conv_label,
        "kpis": {
            "spend": round(spend, 2),
            "leads": int(leads),
            "cpl": conv_cpl,
            "ctr": round(totals.get("ctr", 0) or 0, 2),
            "leadRateFromClick": conv_lead_rate_from_click,
            "purchases": int(totals.get("purchases", 0) or 0),
            "subscribes": int(subscribes),
            "clicks": int(totals.get("clicks", 0) or 0),
            "impressions": int(totals.get("impressions", 0) or 0),
            "reach": int(totals.get("reach", 0) or 0),
            "costPerStart": round(spend / bot_starts, 2) if bot_starts else None,
        },
        "rates": {
            "visitRate": round(totals.get("visitRate", 0) or 0, 1),
            "leadRate": conv_lead_rate,
            "startRate": start["rate"],
        },
        "counts": {
            "linkClicks": int(totals.get("linkClicks", 0) or 0),
            "landingPageViews": int(totals.get("landingPageViews", 0) or 0),
            "leads": int(leads),
            "subscribes": int(subscribes),
            "botStarts": int(bot_starts),
            "telegramLinkClicks": int(link_clicks),
            "formSubmits": int(form_submits),
            "vslPlays": int(vsl_plays),
            "vslKeyMessage": int(vsl_key_message),
        },
        "startSource": start["numeratorSource"],
        "startDenominatorSource": start["denominatorSource"],
        "startScope": start_scope,
        "startHealth": start_health,
        "syncErrors": sync_errors,
    }

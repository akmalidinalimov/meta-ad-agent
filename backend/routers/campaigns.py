"""Live campaign list + live per-campaign KPI bundle for the dashboard.

These read LIVE Meta data on demand (NOT the synced knowledge-base snapshot), so a
just-created / just-running campaign shows up immediately and selecting it returns
fresh KPIs + funnel rates. Both routes sit behind the dashboard session guard (they
are deliberately NOT in app._AUTH_PUBLIC_PATHS).

- GET /api/campaigns/live   — live campaigns, optionally limited to those CREATED in
  the last N days; `force=true` bypasses the 60s live cache (the Refresh button).
- GET /api/campaigns/kpis   — live KPI bundle (spend/leads/CPL/CTR + Visit/Lead/START
  rates) for one campaign, or the whole account when campaignId is omitted/"all".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from ..analysis_engine import summarize_overall, valid_rows
from ..meta_client import get_meta_config
from ..meta_sync import safe_chunked_insights

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


@router.get("/api/campaigns/kpis")
async def campaign_kpis(campaignId: str | None = None, days: int = 30, force: bool = False) -> dict[str, Any]:
    """Live KPI bundle for one campaign (or the whole account when campaignId is omitted
    or "all"), over the last ``days`` days. Reuses analysis_engine.summarize_overall, so
    every rate matches the rest of the app and is capped at 100%. ``force`` is accepted for
    API symmetry with /live; insights are always fetched fresh (uncached)."""
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta is not connected. Add META_ACCESS_TOKEN + META_AD_ACCOUNT_ID."}

    raw = await safe_chunked_insights(config, "campaign_kpis", None, days=days)
    sync_errors = [row["sync_error"] for row in raw if isinstance(row, dict) and row.get("sync_error")]
    rows = valid_rows(raw)

    scoped = bool(campaignId) and campaignId != "all"
    if scoped:
        rows = [row for row in rows if str(row.get("campaign_id")) == str(campaignId)]

    totals = summarize_overall(rows)
    name = next((str(row.get("campaign_name")) for row in rows if row.get("campaign_name")), "") if scoped else ""

    spend = totals.get("spend", 0) or 0
    leads = totals.get("leads", 0) or 0
    subscribes = totals.get("subscribes", 0) or 0

    return {
        "ok": True,
        "source": "live",
        "days": days,
        "campaignId": str(campaignId) if scoped else "all",
        "campaignName": name,
        "hasData": bool(rows),
        "kpis": {
            "spend": round(spend, 2),
            "leads": int(leads),
            "cpl": round(totals.get("cpl", 0) or 0, 2),
            "ctr": round(totals.get("ctr", 0) or 0, 2),
            "leadRateFromClick": round(totals.get("leadRateFromClick", 0) or 0, 2),
            "purchases": int(totals.get("purchases", 0) or 0),
            "subscribes": int(subscribes),
            "clicks": int(totals.get("clicks", 0) or 0),
            "impressions": int(totals.get("impressions", 0) or 0),
            "costPerStart": round(spend / subscribes, 2) if subscribes else None,
        },
        "rates": {
            "visitRate": round(totals.get("visitRate", 0) or 0, 1),
            "leadRate": round(totals.get("leadRate", 0) or 0, 1),
            "startRate": round(totals.get("startRate", 0) or 0, 1),
        },
        "counts": {
            "linkClicks": int(totals.get("linkClicks", 0) or 0),
            "landingPageViews": int(totals.get("landingPageViews", 0) or 0),
            "leads": int(leads),
            "subscribes": int(subscribes),
        },
        "syncErrors": sync_errors,
    }

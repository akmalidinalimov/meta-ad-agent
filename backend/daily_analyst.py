# backend/daily_analyst.py
"""Daily Funnel Analyst orchestration: pull fresh Meta + first-party + CRM data for the
current ad-account day, run the pure metric + decision engines, and return one analysis
object. Best-effort per source - a failing source degrades its section, never the report."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

# today + 3 trailing days for trend context
TRAILING_DAYS = 3

from .analysis_engine import conversion_label
from .audience_creative_metrics import (
    account_norms, aggregate_adsets, ad_metrics, quality_score, rank_creatives,
)
from .daily_recommendations import recommend
from .funnel_events import count_bot_starts, count_event_users
from .meta_client import get_insights, get_meta_config
from .routers.campaigns import _campaign_event_map
from .targets_store import load_targets


async def _crm_today() -> dict[str, Any]:
    """Account-level CRM leads today (no per-audience key yet). Best-effort: zero on failure."""
    # ASYNC and awaited — run_daily_analysis already runs in an event loop; using
    # run_until_complete would crash with 'loop already running'.
    try:
        from .bitrix_client import HttpBitrixTransport, fetch_bitrix_leads, get_bitrix_config
        config = get_bitrix_config()
        if not config.is_configured:
            return {"leads": 0, "stages": {}}
        leads = await asyncio.wait_for(
            fetch_bitrix_leads(transport=HttpBitrixTransport(config), days=1, limit=None), timeout=10.0)
        return {"leads": len(leads), "stages": {}}
    except Exception:  # noqa: BLE001 - CRM is one of several sources
        return {"leads": 0, "stages": {}}


async def run_daily_analysis() -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta not connected.", "audiences": [], "recommendations": []}

    until = date.today()
    since = until - timedelta(days=TRAILING_DAYS)
    try:
        ads = await get_insights(config, level="ad", since=since.isoformat(), until=until.isoformat(), time_increment=None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "audiences": [], "recommendations": []}

    # _campaign_event_map is ASYNC — must be awaited.
    event_map = await _campaign_event_map(config)
    default_event = next(iter(event_map.values()), "LEAD") if event_map else "LEAD"

    enriched: list[dict[str, Any]] = []
    for row in ads:
        event = event_map.get(str(row.get("campaign_id")), default_event)
        enriched.append({**row, "_event": event})
    event_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        event_buckets[row["_event"]].append(row)
    adset_rows: list[dict[str, Any]] = []
    for evt, bucket in event_buckets.items():
        adset_rows.extend(aggregate_adsets(bucket, conversion_event=evt))
    norms = account_norms(adset_rows)

    # count_bot_starts / count_event_users called with no window kwargs — full history
    # consistent with how the dashboard's account-wide START rate is computed.
    bot_starts = count_bot_starts()
    link_clicks = count_event_users("telegram_link_click")
    account_start_rate = (bot_starts / link_clicks * 100) if link_clicks else 0.0

    by_adset: dict[str, list[dict[str, Any]]] = {}
    for row in enriched:
        by_adset.setdefault(str(row.get("adset_id")), []).append(
            ad_metrics(row, conversion_event=row["_event"]))

    audiences: list[dict[str, Any]] = []
    for adset in adset_rows:
        scored = {**adset, "startRate": account_start_rate}
        # quality_score(metric, norms, *, account_start_rate) — account_start_rate is a
        # percent (0-100); guard against 0 denominator in the score's START component.
        quality = quality_score(scored, norms, account_start_rate=account_start_rate or 1.0)
        audiences.append({**scored, "quality": quality,
                          "creatives": rank_creatives(by_adset.get(adset["adsetId"], []), norms=norms)})
    audiences.sort(key=lambda a: (a["quality"], a["leads"]), reverse=True)

    total_spend = sum(a["spend"] for a in audiences)
    total_leads = sum(a["leads"] for a in audiences)
    targets = load_targets()
    crm = await _crm_today()
    rates = {
        "spend": round(total_spend, 2),
        "leads": total_leads,
        "cpl": round(total_spend / total_leads, 2) if total_leads else None,
        "startRate": round(account_start_rate, 1),
        "crmLeads": crm["leads"],
        "conversionLabel": conversion_label(default_event),
    }
    recs = recommend(audiences, total_conversions=total_leads, targets=targets)
    return {"ok": True, "date": until.isoformat(), "rates": rates, "targets": targets,
            "audiences": audiences, "recommendations": recs, "qualityIsProxy": True}

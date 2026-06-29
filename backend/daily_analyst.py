# backend/daily_analyst.py
"""Daily Funnel Analyst orchestration: pull fresh Meta + first-party + CRM data for the
current ad-account day, run the pure metric + decision engines, and return one analysis
object. Best-effort per source - a failing source degrades its section, never the report."""
from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

# today + 3 trailing days for trend context
TRAILING_DAYS = 3

from .analysis_engine import conversion_label, count_conversion
from .audience_creative_metrics import (
    account_norms, aggregate_adsets, ad_metrics, quality_score, rank_creatives,
    safe_float,
)
from .daily_recommendations import detect_anomalies, recommend
from .funnel_events import count_bot_starts, count_event_users
from .meta_client import get_insights, get_meta_config
from .routers.campaigns import _campaign_event_map
from .targets_store import load_targets


async def _crm_today() -> dict[str, Any]:
    """Account-level CRM leads today (no per-audience key yet). Best-effort: zero on failure."""
    # ASYNC and awaited — run_daily_analysis already runs in an event loop; using
    # run_until_complete would crash with 'loop already running'.
    try:
        from .bitrix_client import HttpBitrixTransport, fetch_bitrix_leads, get_bitrix_config, tashkent_day
        config = get_bitrix_config()
        if not config.is_configured:
            return {"leads": 0, "stages": {}}
        title = os.getenv("BITRIX_LEAD_SOURCE_TITLE", "AI Creators 5.0 buyurtmasi").strip()
        # Fetch a 2-day buffer (Bitrix DATE_CREATE is +03:00) then keep only leads whose
        # Asia/Tashkent calendar day is today — matching the dashboard's cost-per-lead count
        # (title-scoped to THIS funnel, not the whole multi-course Bitrix portal).
        leads = await asyncio.wait_for(
            fetch_bitrix_leads(transport=HttpBitrixTransport(config), days=2, limit=None, title_contains=title or None),
            timeout=10.0)
        today = (datetime.now(timezone.utc) + timedelta(hours=5)).date().isoformat()
        n = sum(1 for lead in leads if tashkent_day(lead.get("createdAt")) == today)
        return {"leads": n, "stages": {}}
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
    # Aggregate per conversion event AND compute norms PER event, so a registration-optimized
    # audience (a deeper, structurally pricier event) is judged against its own peers — not the
    # cheap click campaign's median, which would false-flag every registration as "expensive".
    adset_rows: list[dict[str, Any]] = []
    norms_by_event: dict[str, dict[str, float]] = {}
    for evt, bucket in event_buckets.items():
        rows = aggregate_adsets(bucket, conversion_event=evt)
        norms_by_event[evt] = account_norms(rows)
        for r in rows:
            r["conversionEvent"] = evt
        adset_rows.extend(rows)

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
        evt = adset.get("conversionEvent", default_event)
        norms = norms_by_event.get(evt, {})
        scored = {**adset, "startRate": account_start_rate}
        # quality_score(metric, norms, *, account_start_rate) — account_start_rate is a
        # percent (0-100); guard against 0 denominator in the score's START component.
        quality = quality_score(scored, norms, account_start_rate=account_start_rate or 1.0)
        audiences.append({**scored, "quality": quality,
                          "conversionLabel": conversion_label(evt),
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


async def intraday_anomaly_alerts() -> list[dict[str, Any]]:
    """Account-level intra-day guardrail for the 4-hourly loop: today's CPL/spend/leads vs a
    7-day baseline CPL + the operator's targets. Best-effort -> [] on any failure/not-configured."""
    config = get_meta_config()
    if not config.is_configured:
        return []
    try:
        today_rows = await get_insights(config, level="account", date_preset="today", time_increment=None)
        base_rows = await get_insights(config, level="account", date_preset="last_7d", time_increment=None)
    except Exception:  # noqa: BLE001
        return []
    try:
        event_map = await _campaign_event_map(config)
    except Exception:  # noqa: BLE001
        event_map = {}
    default_event = next(iter(event_map.values()), "LEAD") if event_map else "LEAD"

    def _agg(rows: list[dict[str, Any]]) -> tuple[float, int]:
        spend = sum(safe_float(r.get("spend")) for r in rows)
        leads = int(sum(count_conversion(r, default_event) for r in rows))
        return spend, leads

    t_spend, t_leads = _agg(today_rows)
    b_spend, b_leads = _agg(base_rows)
    today = {"cpl": round(t_spend / t_leads, 2) if t_leads else None, "spend": round(t_spend, 2), "leads": t_leads}
    baseline = {"cpl": round(b_spend / b_leads, 2) if b_leads else None}
    return detect_anomalies(today, baseline, targets=load_targets())

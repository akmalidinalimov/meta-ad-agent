"""Landing-page / ChatPlace funnel event ingestion routes."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..analysis_engine import summarize_overall, valid_rows
from ..api_models import FunnelEventRequest
from ..chatplace_events import normalize_chatplace_event
from ..funnel_events import (
    build_funnel_summary,
    count_bot_starts,
    count_event_users,
    save_funnel_event,
    select_start_rate,
)
from ..meta_client import get_meta_config
from ..meta_sync import safe_chunked_insights

router = APIRouter()


@router.post("/api/funnel/events")
def ingest_funnel_event(request: FunnelEventRequest) -> dict[str, Any]:
    event = save_funnel_event(request.event)
    return {"ok": True, "event": event, "summary": build_funnel_summary()}


@router.post("/api/chatplace/events")
async def ingest_chatplace_event(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("CHATPLACE_WEBHOOK_SECRET", "").strip()
    provided_secret = str(payload.get("secret") or request.headers.get("x-chatplace-secret") or "").strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid ChatPlace webhook secret.")

    event_payload = normalize_chatplace_event(payload)
    event = save_funnel_event(event_payload)
    return {
        "ok": True,
        "tracking_status": "saved",
        "visitor_id": event.get("visitorId"),
        "event_name": event.get("eventName"),
        "telegram_user_id": event.get("telegramUserId"),
        "summary": build_funnel_summary(),
    }


@router.get("/api/funnel/summary")
def funnel_event_summary() -> dict[str, Any]:
    return build_funnel_summary()


@router.get("/api/funnel/rates")
async def funnel_rates(campaign_id: str | None = None, days: int = 30) -> dict[str, Any]:
    """Live ad-funnel rates.

    visitRate = landing page views / link clicks            (Meta; capped 100%)
    leadRate  = leads / landing page views                  (Meta; capped 100%)
    startRate = bot starts / Telegram-button clicks         (first-party; see below)

    visitRate and leadRate come straight from analysis_engine (Meta data, capped
    in finalize_metrics). startRate is computed here by select_start_rate and is
    INDEPENDENT of leadRate: its numerator is the deduped first-party Telegram
    bot-start relay (Meta 'subscribe' only as a fallback), and its denominator
    prefers the deduped first-party telegram_link_click ("clicked the button to
    Telegram") — falling back to Meta 'leads' only while the landing-page tracker
    isn't firing. ``startDenominatorSource`` tells the UI which one was used so a
    proxy denominator is never mistaken for the exact button-click rate. Behind
    the normal dashboard auth (NOT in the public ingest set).
    """
    config = get_meta_config()
    if not config.is_configured:
        return {
            "ok": False,
            "error": "Meta is not connected. Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to backend/.env.",
        }

    raw = await safe_chunked_insights(config, "funnel_rates", None, days=days)
    sync_errors = [row["sync_error"] for row in raw if row.get("sync_error")]
    rows = valid_rows(raw)
    if campaign_id:
        rows = [row for row in rows if str(row.get("campaign_id")) == str(campaign_id)]

    totals = summarize_overall(rows)
    leads = totals.get("leads", 0)

    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    bot_starts = count_bot_starts(since_iso=since_iso)
    link_clicks = count_event_users("telegram_link_click", since_iso=since_iso)
    subscribes = totals.get("subscribes", 0)
    start = select_start_rate(
        bot_starts=bot_starts, subscribes=subscribes, link_clicks=link_clicks, leads=leads
    )

    return {
        "ok": True,
        "days": days,
        "campaignId": campaign_id,
        "counts": {
            "linkClicks": totals.get("linkClicks", 0),
            "landingPageViews": totals.get("landingPageViews", 0),
            "leads": leads,
            "botStarts": bot_starts,
            "telegramLinkClicks": link_clicks,
            "subscribes": subscribes,
        },
        "rates": {
            "visitRate": round(totals.get("visitRate", 0), 1),
            "leadRate": round(totals.get("leadRate", 0), 1),
            "startRate": start["rate"],
        },
        "startSource": start["numeratorSource"],
        "startDenominatorSource": start["denominatorSource"],
        "hasData": bool(rows),
        "syncErrors": sync_errors,
    }

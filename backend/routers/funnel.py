"""Landing-page / ChatPlace funnel event ingestion + per-day funnel history routes."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..api_models import FunnelEventRequest
from ..chatplace_events import normalize_chatplace_event
from ..funnel_events import build_funnel_summary, load_funnel_events, save_funnel_event
from ..funnel_history import (
    build_history_series,
    crm_leads_by_date,
    daily_meta_metrics,
    daterange,
    event_users_by_date,
    load_vsl_snapshots,
    record_vsl_snapshot,
)
from ..meta_client import get_meta_config
from ..meta_sync import normalize_sync_days, safe_chunked_insights

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


async def _crm_leads_by_date(days: int) -> dict[str, int]:
    """Per-day CRM-lead counts from Bitrix for the configured source title (the same
    source the CRM card uses). Best-effort: returns {} when Bitrix isn't configured or
    the read fails, so a CRM hiccup never blanks the whole trend."""
    from ..bitrix_client import HttpBitrixTransport, fetch_bitrix_leads, get_bitrix_config

    config = get_bitrix_config()
    if not config.is_configured:
        return {}
    title = os.getenv("BITRIX_LEAD_SOURCE_TITLE", "AI Creators 5.0 buyurtmasi").strip()
    try:
        leads = await fetch_bitrix_leads(
            transport=HttpBitrixTransport(config), days=days, limit=None, title_contains=title or None
        )
    except Exception:  # noqa: BLE001 - best-effort; CRM is one of several series
        return {}
    return crm_leads_by_date(leads)


async def _vsl_views_now(days: int) -> float | None:
    """Current cumulative VSL view count from YouTube, or None when not configured/failed."""
    from ..youtube_client import HttpYouTubeTransport, build_vsl_report, get_youtube_config

    config = get_youtube_config()
    if not config.is_configured:
        return None
    try:
        report = await build_vsl_report(transport=HttpYouTubeTransport(config), config=config, days=days)
    except Exception:  # noqa: BLE001 - VSL is optional
        return None
    views = report.get("views")
    try:
        return float(views) if views is not None else None
    except (TypeError, ValueError):
        return None


def _parse_day(value: str | None) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@router.get("/api/funnel/history")
async def funnel_history(
    campaignId: str | None = None,
    days: int = 30,
    since: str | None = None,
    until: str | None = None,
    granularity: str = "day",
    force: bool = False,
) -> dict[str, Any]:
    """Per-day funnel history for one campaign (or the whole account when campaignId is
    omitted/"all"). Read-only, behind the dashboard session guard. The window is the last
    ``days`` days, OR an explicit ``since``..``until`` (YYYY-MM-DD) range when both are
    given. Each point carries the day's COUNTS (the frontend derives visit/lead/VSL-view/
    CRM-fill with the same computeSimpleFunnel as the live cards) plus the backend START
    rate. VSL daily views accrue forward from a daily snapshot (YouTube reports only a
    running total, so they can't be backfilled). ``force``/``granularity`` are accepted
    for API symmetry; insights are always fetched fresh and the granularity is daily."""
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta is not connected.", "points": [], "days": days}

    scoped = bool(campaignId) and campaignId != "all"

    # Resolve the window: an explicit since..until range wins; otherwise the last N days.
    end_day = _parse_day(until) or date.today()
    start_day = _parse_day(since)
    if start_day and start_day <= end_day:
        days = normalize_sync_days((end_day - start_day).days + 1)
    else:
        days = normalize_sync_days(days)
    start_day = end_day - timedelta(days=days - 1)  # clamp to the supported max window

    raw = await safe_chunked_insights(config, "funnel_history", None, days=days, end_date=end_day)
    sync_errors = [row["sync_error"] for row in raw if isinstance(row, dict) and row.get("sync_error")]
    meta_by_date = daily_meta_metrics(raw, campaignId if scoped else None)

    events = load_funnel_events()
    bot_starts_by_date = event_users_by_date(events, "bot_start")
    link_clicks_by_date = event_users_by_date(events, "telegram_link_click")
    crm_by_date = await _crm_leads_by_date(days)

    # VSL daily views accrue from the YouTube view count: record today's cumulative count,
    # then the day-over-day delta of the snapshots is the per-day views. (YouTube reports
    # only a running total, so daily VSL history builds up from the first snapshot forward.)
    vsl_views_now = await _vsl_views_now(days)
    if vsl_views_now is not None:
        record_vsl_snapshot(date.today().isoformat(), vsl_views_now)
    vsl_cumulative_by_date = load_vsl_snapshots()

    dates = daterange(start_day, end_day)
    points = build_history_series(
        dates=dates,
        meta_by_date=meta_by_date,
        bot_starts_by_date=bot_starts_by_date,
        link_clicks_by_date=link_clicks_by_date,
        crm_by_date=crm_by_date,
        vsl_cumulative_by_date=vsl_cumulative_by_date,
        today=date.today().isoformat(),
    )
    return {
        "ok": True,
        "source": "live",
        "days": days,
        "granularity": "day",
        "since": start_day.isoformat(),
        "until": end_day.isoformat(),
        "campaignId": str(campaignId) if scoped else "all",
        "vslConfigured": vsl_views_now is not None,
        "points": points,
        "syncErrors": sync_errors,
        "notes": {
            "vsl": "VSL daily views are the day-over-day change in YouTube's view count — it reports only a running total, so the daily line builds up from the first snapshot forward.",
            "botStarts": "Bot starts/button clicks are first-party daily uniques and are attributed account-wide (not per campaign).",
        },
    }

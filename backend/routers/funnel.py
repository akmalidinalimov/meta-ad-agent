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
from ..meta_client import MetaApiError, get_entity_insights, get_insights, get_meta_config
from ..meta_sync import normalize_sync_days

router = APIRouter()


@router.post("/api/funnel/events")
def ingest_funnel_event(request: FunnelEventRequest) -> dict[str, Any]:
    # Append-only. Do NOT compute build_funnel_summary() here: this is the highest-volume
    # endpoint (the landing tracker fires it constantly and ignores the response body), and
    # the summary re-reads + JSON-parses the ENTIRE ever-growing event log (twice). Doing
    # that per ingest is O(total events) per request and ratchets RSS up under concurrency
    # until the VM swap-thrashes (prod outage 2026-06-21). The summary is available on demand
    # at GET /api/funnel/summary.
    event = save_funnel_event(request.event)
    return {"ok": True, "event": event}


@router.post("/api/chatplace/events")
async def ingest_chatplace_event(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("CHATPLACE_WEBHOOK_SECRET", "").strip()
    provided_secret = str(payload.get("secret") or request.headers.get("x-chatplace-secret") or "").strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid ChatPlace webhook secret.")

    event_payload = normalize_chatplace_event(payload)
    event = save_funnel_event(event_payload)
    # Append-only — no per-ingest build_funnel_summary() (see ingest_funnel_event above for
    # why: full-history reparse per request is the memory-wedge driver).
    return {
        "ok": True,
        "tracking_status": "saved",
        "visitor_id": event.get("visitorId"),
        "event_name": event.get("eventName"),
        "telegram_user_id": event.get("telegramUserId"),
    }


@router.get("/api/funnel/summary")
def funnel_event_summary() -> dict[str, Any]:
    return build_funnel_summary()


async def _crm_leads_by_date(days: int) -> dict[str, int]:
    """Per-day CRM-lead counts from Bitrix, BOT-only (Cell B) — the same bot leads the CRM
    card counts, so the trend's CRM-fill line matches the headline. Best-effort: returns {}
    when Bitrix isn't configured or the read fails, so a CRM hiccup never blanks the trend."""
    from ..bitrix_client import (
        HttpBitrixTransport, fetch_bitrix_leads, get_bitrix_config, get_bot_cell_tags, lead_source_title,
    )
    from ..crm_funnel import split_by_cell

    config = get_bitrix_config()
    if not config.is_configured:
        return {}
    title = lead_source_title()  # all AI-Creators lead variants (matches the dashboard cost-per-lead)
    try:
        leads = await fetch_bitrix_leads(
            transport=HttpBitrixTransport(config), days=days, limit=None, title_contains=title or None
        )
    except Exception:  # noqa: BLE001 - best-effort; CRM is one of several series
        return {}
    descs, utms = get_bot_cell_tags()
    bot_leads = split_by_cell(leads, bot_source_descriptions=descs, bot_utm_contents=utms)["B"]
    return crm_leads_by_date(bot_leads)


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

    # COMPLETE per-campaign daily insights: a selected campaign via its OWN endpoint, "all"
    # at CAMPAIGN level — both avoid the account-wide ad-daily page cap that dropped
    # smaller/newer campaigns (so a scoped trend isn't all zeros). rows are already scoped,
    # so daily_meta_metrics groups by date only.
    s_iso, u_iso = start_day.isoformat(), end_day.isoformat()
    sync_errors: list[str] = []
    try:
        if scoped:
            raw = await get_entity_insights(config, str(campaignId), since=s_iso, until=u_iso, time_increment=1)
        else:
            raw = await get_insights(config, level="campaign", since=s_iso, until=u_iso, time_increment=1)
    except MetaApiError as exc:
        raw = []
        sync_errors = [str(exc)]
    meta_by_date = daily_meta_metrics(raw, None)

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

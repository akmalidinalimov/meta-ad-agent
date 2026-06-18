"""Per-day funnel history — the time-series behind the dashboard's trend charts.

Each funnel rate (visit / lead / start / VSL-view / CRM-fill) gets a daily value so
the operator can see whether it is climbing or sliding over the last N days. The series
is built from the SAME live sources the live cards use, so a given day's numbers match
what the dashboard would have shown on that day:

- Meta daily insights (time_increment=1 → one row per day) → per-day spend, link clicks,
  landing views, leads, subscribes (reusing analysis_engine.aggregate_rows so the metric
  extraction is identical to the rest of the app).
- First-party funnel events → per-day unique bot starts + Telegram button clicks.
- Bitrix leads → per-day CRM-lead counts (by DATE_CREATE).
- YouTube VSL views → cumulative only, so daily VSL views are derived as the day-over-day
  DELTA of a daily snapshot (storage/funnel_history.jsonl). VSL history can't be
  backfilled (YouTube only reports a running total), so it accrues from the first snapshot
  forward; earlier days report vslViews = null.

The endpoint returns per-day COUNTS plus the backend START rate (select_start_rate); the
frontend computes the other four rates from the counts with the same computeSimpleFunnel
it uses for the live cards, so the trend line and the headline card can never disagree.
All reads are read-only.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .analysis_engine import aggregate_rows, valid_rows
from .funnel_events import STORAGE_DIR, select_start_rate

HISTORY_PATH = STORAGE_DIR / "funnel_history.jsonl"


# --- per-day aggregation (pure) --------------------------------------------------------


def daily_meta_metrics(rows: list[dict[str, Any]], campaign_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Group daily Meta insight rows by their date (date_start) and aggregate each day
    with the app's shared aggregate_rows, so per-day spend/clicks/leads/etc. are
    extracted exactly like the live cards. Optionally scoped to one campaign."""
    scoped = bool(campaign_id) and campaign_id != "all"
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows(rows):
        if scoped and str(row.get("campaign_id")) != str(campaign_id):
            continue
        day = str(row.get("date_start") or row.get("date") or "")[:10]
        if not day:
            continue
        by_date[day].append(row)
    return {day: aggregate_rows(rs) for day, rs in by_date.items()}


def event_users_by_date(events: list[dict[str, Any]], event_name: str) -> dict[str, int]:
    """Per-day count of UNIQUE users who fired ``event_name`` (deduped by Telegram user,
    falling back to visitor id) — the same dedup as funnel_events.count_event_users, so a
    repeat on the same day isn't double-counted. Date taken from receivedAt (UTC)."""
    seen: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.get("eventName") != event_name:
            continue
        day = str(event.get("receivedAt") or "")[:10]
        if not day:
            continue
        identity = event.get("telegramUserId") or event.get("visitorId")
        if identity:
            seen[day].add(str(identity))
    return {day: len(users) for day, users in seen.items()}


def crm_leads_by_date(leads: list[dict[str, Any]]) -> dict[str, int]:
    """Per-day CRM-lead count by Bitrix DATE_CREATE (the leads passed in are already
    filtered to the configured source/order title by the caller)."""
    counts: Counter[str] = Counter()
    for lead in leads:
        created = str(lead.get("createdAt") or "")[:10]
        if created:
            counts[created] += 1
    return dict(counts)


def daterange(start_date: date, end_date: date) -> list[str]:
    """Inclusive list of YYYY-MM-DD strings from start_date to end_date."""
    days: list[str] = []
    current = start_date
    while current <= end_date:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def build_history_series(
    *,
    dates: list[str],
    meta_by_date: dict[str, dict[str, Any]],
    bot_starts_by_date: dict[str, int],
    link_clicks_by_date: dict[str, int],
    crm_by_date: dict[str, int],
    vsl_cumulative_by_date: dict[str, float] | None = None,
    vsl_daily_by_date: dict[str, int] | None = None,
    today: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble the per-day points. Each point carries the day's COUNTS (so the frontend
    derives visit/lead/VSL-view/CRM-fill with computeSimpleFunnel) plus the backend START
    rate for that day. The current server day (``today``) is flagged ``incomplete`` because
    its conversion-based rates (lead/start/CRM) keep climbing as the day finishes and Meta
    attributes late conversions.

    VSL daily views come from ``vsl_daily_by_date`` (real per-day views from YouTube
    Analytics, including backfill) when available; otherwise they fall back to the
    day-over-day delta of a cumulative snapshot (``vsl_cumulative_by_date``), which is null
    until at least two snapshots exist."""
    vsl_cumulative_by_date = vsl_cumulative_by_date or {}
    points: list[dict[str, Any]] = []
    last_cumulative: float | None = None
    for day in dates:
        metrics = meta_by_date.get(day, {})
        link_clicks = int(metrics.get("linkClicks", 0) or 0)
        landing_views = int(metrics.get("landingPageViews", 0) or 0)
        leads = int(metrics.get("leads", 0) or 0)
        subscribes = int(metrics.get("subscribes", 0) or 0)
        spend = float(metrics.get("spend", 0) or 0)
        bot_starts = int(bot_starts_by_date.get(day, 0))
        tg_link_clicks = int(link_clicks_by_date.get(day, 0))
        crm_leads = int(crm_by_date.get(day, 0))

        # VSL daily views: prefer real per-day data (YouTube Analytics) when present;
        # otherwise derive from the cumulative snapshot's day-over-day delta.
        vsl_views: int | None = None
        if vsl_daily_by_date is not None:
            if day in vsl_daily_by_date:
                vsl_views = int(vsl_daily_by_date[day])
        elif day in vsl_cumulative_by_date:
            cumulative = float(vsl_cumulative_by_date[day])
            if last_cumulative is not None and cumulative >= last_cumulative:
                vsl_views = int(round(cumulative - last_cumulative))
            last_cumulative = cumulative

        start = select_start_rate(
            bot_starts=bot_starts, subscribes=subscribes, link_clicks=tg_link_clicks, leads=leads
        )
        points.append(
            {
                "date": day,
                "incomplete": today is not None and day == today,
                "spend": round(spend, 2),
                "startRate": start["rate"],
                "startDenominatorSource": start["denominatorSource"],
                "counts": {
                    "linkClicks": link_clicks,
                    "landingViews": landing_views,
                    "leads": leads,
                    "botStarts": bot_starts,
                    "telegramLinkClicks": tg_link_clicks,
                    "subscribes": subscribes,
                    "crmLeads": crm_leads,
                    "vslViews": vsl_views,
                },
            }
        )
    return points


# --- daily VSL snapshot store (forward-accruing; YouTube gives only a running total) ---


def load_vsl_snapshots(*, storage_dir: Path = STORAGE_DIR) -> dict[str, float]:
    """date (YYYY-MM-DD) -> the day's cumulative VSL view count. We keep the MAX seen for a
    date, not the latest: YouTube's lifetime viewCount wobbles down by ~tens as it removes
    invalid views, and a downward wobble would otherwise produce a negative daily delta."""
    path = storage_dir / "funnel_history.jsonl"
    if not path.exists():
        return {}
    snapshots: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        day = str(record.get("date") or "")[:10]
        value = record.get("vslViews")
        if day and value is not None:
            try:
                snapshots[day] = max(snapshots.get(day, 0.0), float(value))
            except (TypeError, ValueError):
                continue
    return snapshots


def record_vsl_snapshot(
    date_str: str, cumulative_views: float | int | None, *, storage_dir: Path = STORAGE_DIR
) -> None:
    """Record today's cumulative VSL views so a daily delta becomes computable. No-op when
    VSL isn't configured (None) or when the value isn't a new daily high — that keeps the
    log from filling with YouTube's minute-to-minute wobble and preserves the day's peak."""
    if cumulative_views is None:
        return
    day = str(date_str)[:10]
    try:
        value = float(cumulative_views)
    except (TypeError, ValueError):
        return
    if value <= load_vsl_snapshots(storage_dir=storage_dir).get(day, 0.0):
        return  # not a new high for the day → skip (avoids noise + downward wobble)
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / "funnel_history.jsonl"
    record = {"date": day, "vslViews": value, "recordedAt": datetime.now(timezone.utc).isoformat()}
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")

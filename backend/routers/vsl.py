"""VSL (YouTube) watch-through metrics route.

Read-only. Returns total Views (primary) + the 50%-watched view count and rate
(from YouTube audience retention). Sits behind the dashboard session guard.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..youtube_client import HttpYouTubeTransport, build_vsl_report, get_youtube_config

router = APIRouter()


def build_youtube_transport(config: Any) -> Any:
    return HttpYouTubeTransport(config)


def _period_views(snapshots: dict[str, float], since: str, until: str) -> int | None:
    """Views inside [since, until] from the cumulative view-count snapshots. Daily deltas
    telescope, so the period total = (cumulative on/before `until`) − (cumulative before
    `since`). None when there is no baseline snapshot before the period (can't yet diff)."""
    end_cum = None
    start_cum = None
    for day in sorted(snapshots):
        if day <= until:
            end_cum = snapshots[day]
        if day < since:
            start_cum = snapshots[day]
    if end_cum is None or start_cum is None:
        return None
    return max(0, int(round(end_cum - start_cum)))


@router.get("/api/vsl")
async def vsl_metrics(
    days: int = 30, since: str | None = None, until: str | None = None, force: bool = False
) -> dict[str, Any]:  # force: cache-bust only (uncached)
    config = get_youtube_config()
    if not config.is_configured:
        return {
            "ok": False,
            "configured": False,
            "error": "YouTube not configured. Set YOUTUBE_VSL_VIDEO_ID plus YOUTUBE_API_KEY (views) and/or YOUTUBE_OAUTH_* (50% retention).",
            "views": None,
            "viewsWatched50": None,
            "watchRate50": None,
            "hasRetention": False,
        }
    try:
        report = await build_vsl_report(transport=build_youtube_transport(config), config=config, days=days)
    except Exception as exc:  # noqa: BLE001 - surface a sanitized 502
        raise HTTPException(status_code=502, detail=f"YouTube read failed: {exc}") from exc
    report["ok"] = True
    report["configured"] = True
    report["videoId"] = config.video_id
    report["days"] = days
    report["refreshedAt"] = datetime.now(timezone.utc).isoformat()

    # For a bounded date range, also return the period's views = the change in the
    # cumulative count across the window (YouTube only gives a running total). `views`
    # stays the lifetime cumulative; `periodViews` is the scoped number the card uses.
    if since and until:
        from ..funnel_history import load_vsl_snapshots, record_vsl_snapshot

        record_vsl_snapshot(date.today().isoformat(), report.get("views"))
        report["scoped"] = True
        report["since"] = str(since)[:10]
        report["until"] = str(until)[:10]
        report["periodViews"] = _period_views(load_vsl_snapshots(), report["since"], report["until"])
    return report

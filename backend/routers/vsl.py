"""VSL (YouTube) watch-through metrics route.

Read-only. Returns total Views (primary) + the 50%-watched view count and rate
(from YouTube audience retention). Sits behind the dashboard session guard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..youtube_client import HttpYouTubeTransport, build_vsl_report, get_youtube_config

router = APIRouter()


def build_youtube_transport(config: Any) -> Any:
    return HttpYouTubeTransport(config)


@router.get("/api/vsl")
async def vsl_metrics(days: int = 30) -> dict[str, Any]:
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
    return report

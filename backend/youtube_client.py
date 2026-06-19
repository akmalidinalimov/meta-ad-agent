from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from .meta_client import get_ssl_context

load_dotenv()

DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2"
TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class YouTubeConfig:
    api_key: str
    oauth_client_id: str
    oauth_client_secret: str
    oauth_refresh_token: str
    video_id: str

    @property
    def has_oauth(self) -> bool:
        return bool(self.oauth_client_id and self.oauth_client_secret and self.oauth_refresh_token)

    @property
    def is_configured(self) -> bool:
        # Need a video id, plus at least one way to read views (Data API key or OAuth).
        return bool(self.video_id and (self.api_key or self.has_oauth))


def get_youtube_config() -> YouTubeConfig:
    return YouTubeConfig(
        api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
        oauth_client_id=os.getenv("YOUTUBE_OAUTH_CLIENT_ID", "").strip(),
        oauth_client_secret=os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET", "").strip(),
        oauth_refresh_token=os.getenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "").strip(),
        video_id=os.getenv("YOUTUBE_VSL_VIDEO_ID", "").strip(),
    )


# --- pure parsing / math (fully unit-tested) -------------------------------


def parse_view_count(payload: dict[str, Any]) -> int:
    """Total lifetime views from a Data API videos.list?part=statistics response."""
    items = payload.get("items", [])
    if not items:
        return 0
    try:
        return int(items[0].get("statistics", {}).get("viewCount", 0) or 0)
    except (TypeError, ValueError):
        return 0


def parse_retention_rows(payload: dict[str, Any]) -> list[tuple[float, float]]:
    """(elapsedVideoTimeRatio, audienceWatchRatio) pairs from an Analytics report,
    mapped by column name so column order never matters."""
    headers = [h.get("name") for h in payload.get("columnHeaders", [])]
    try:
        ei = headers.index("elapsedVideoTimeRatio")
        ai = headers.index("audienceWatchRatio")
    except ValueError:
        return []
    rows: list[tuple[float, float]] = []
    for row in payload.get("rows", []) or []:
        if len(row) > max(ei, ai):
            try:
                rows.append((float(row[ei]), float(row[ai])))
            except (TypeError, ValueError):
                continue
    return rows


def ratio_nearest_half(rows: list[tuple[float, float]]) -> float | None:
    """audienceWatchRatio at the elapsed point nearest the 50% mark."""
    best: tuple[float, float] | None = None
    for elapsed, ratio in rows:
        distance = abs(elapsed - 0.5)
        if best is None or distance < best[0]:
            best = (distance, ratio)
    return best[1] if best else None


def build_vsl_metrics(views: Any, watch_ratio_half: float | None) -> dict[str, Any]:
    """Views + the 50%-watched view count and rate.

    watch_ratio_half is audienceWatchRatio at ~50% elapsed = (midpoint watches /
    total views). It can exceed 1 when viewers rewind, so it is clamped to [0,1]
    before being turned into a viewer count (a viewer can't be counted more than once).
    """
    try:
        views_int = max(0, int(views or 0))
    except (TypeError, ValueError):
        views_int = 0
    if watch_ratio_half is None:
        return {"views": views_int, "viewsWatched50": None, "watchRate50": None}
    ratio = max(0.0, min(1.0, float(watch_ratio_half)))
    return {
        "views": views_int,
        "viewsWatched50": round(views_int * ratio),
        "watchRate50": round(ratio * 100, 1),
    }


# --- transport (HTTP; read-only) -------------------------------------------


class YouTubeTransport(Protocol):
    async def fetch_views(self, video_id: str) -> int:
        ...

    async def fetch_retention_rows(self, video_id: str, days: int) -> list[tuple[float, float]]:
        ...


class HttpYouTubeTransport:
    """Read-only YouTube transport. Views via the Data API (key) when available,
    otherwise the Analytics API; retention always via the Analytics API (OAuth)."""

    def __init__(self, config: YouTubeConfig):
        self.config = config

    async def _access_token(self) -> str:
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.config.oauth_client_id,
                    "client_secret": self.config.oauth_client_secret,
                    "refresh_token": self.config.oauth_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"YouTube OAuth token refresh returned HTTP {response.status_code}.")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("YouTube OAuth token refresh did not return an access token.")
        return token

    async def fetch_views(self, video_id: str) -> int:
        if self.config.api_key:
            url = f"{DATA_API}/videos"
            params = {"part": "statistics", "id": video_id, "key": self.config.api_key}
            async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
                response = await client.get(url, params=params)
            if response.status_code >= 400:
                raise RuntimeError(f"YouTube Data API returned HTTP {response.status_code}.")
            return parse_view_count(response.json())
        # OAuth-only fallback: Analytics `views` over a wide window.
        token = await self._access_token()
        start = (date.today() - timedelta(days=3650)).isoformat()
        params = {
            "ids": "channel==MINE",
            "startDate": start,
            "endDate": date.today().isoformat(),
            "metrics": "views",
            "filters": f"video=={video_id}",
        }
        payload = await self._analytics_query(token, params)
        rows = payload.get("rows", []) or []
        try:
            return int(rows[0][0]) if rows else 0
        except (TypeError, ValueError, IndexError):
            return 0

    async def fetch_retention_rows(self, video_id: str, days: int) -> list[tuple[float, float]]:
        token = await self._access_token()
        start = (date.today() - timedelta(days=days)).isoformat()
        params = {
            "ids": "channel==MINE",
            "startDate": start,
            "endDate": date.today().isoformat(),
            "metrics": "audienceWatchRatio",
            "dimensions": "elapsedVideoTimeRatio",
            "filters": f"video=={video_id}",
        }
        payload = await self._analytics_query(token, params)
        return parse_retention_rows(payload)

    async def _analytics_query(self, token: str, params: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.get(
                f"{ANALYTICS_API}/reports",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"YouTube Analytics API returned HTTP {response.status_code}.")
        return response.json()


async def build_vsl_report(*, transport: YouTubeTransport, config: YouTubeConfig, days: int) -> dict[str, Any]:
    """Views (primary) + 50%-watched (secondary). Retention is only attempted when
    OAuth is configured; otherwise the report shows views with null watch metrics."""
    views = await transport.fetch_views(config.video_id)
    ratio_half: float | None = None
    if config.has_oauth:
        rows = await transport.fetch_retention_rows(config.video_id, days)
        ratio_half = ratio_nearest_half(rows)
    metrics = build_vsl_metrics(views, ratio_half)
    metrics["hasRetention"] = ratio_half is not None
    metrics["source"] = "youtube_analytics" if config.has_oauth else "youtube_data"
    return metrics

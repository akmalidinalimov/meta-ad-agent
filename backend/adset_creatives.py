"""Scoped per-ad-set creative fetch + performance ranking.

Shared by the Telegram drill-down and the web-app creatives view so both surfaces
rank creatives identically. Ads are fetched scoped to ONE ad set (so the account-wide
ad page limit can't drop them) and ranked by lifetime performance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Conversion actions worth ranking creatives by, best-result-first. The first type
# present on an ad becomes its headline "result" (Meta reports several aliases).
RESULT_ACTION_TYPES: list[tuple[str, str]] = [
    ("offsite_conversion.fb_pixel_purchase", "purchases"),
    ("purchase", "purchases"),
    ("onsite_conversion.purchase", "purchases"),
    ("offsite_conversion.fb_pixel_lead", "leads"),
    ("onsite_conversion.lead_grouped", "leads"),
    ("lead", "leads"),
    ("complete_registration", "registrations"),
    ("onsite_conversion.messaging_conversation_started_7d", "chats started"),
    ("link_click", "link clicks"),
]


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def ad_results(actions: list[dict[str, Any]] | None) -> tuple[float, str | None]:
    """Pick the highest-priority conversion result reported for an ad."""
    if not actions:
        return 0.0, None
    by_type = {a.get("action_type"): to_float(a.get("value")) for a in actions}
    for action_type, label in RESULT_ACTION_TYPES:
        if action_type in by_type and by_type[action_type] > 0:
            return by_type[action_type], label
    return 0.0, None


def rank_creatives(ads: list[dict[str, Any]], insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach per-ad performance from insights and sort best-performing first."""
    by_ad = {str(row.get("ad_id")): row for row in (insights or [])}
    enriched: list[dict[str, Any]] = []
    for ad in ads or []:
        row = by_ad.get(str(ad.get("id")), {})
        results, results_label = ad_results(row.get("actions"))
        ad = {
            **ad,
            "_perf": {
                "impressions": int(to_float(row.get("impressions"))),
                "clicks": int(to_float(row.get("clicks"))),
                "spend": to_float(row.get("spend")),
                "ctr": to_float(row.get("ctr")),
                "results": results,
                "results_label": results_label,
                "has_data": bool(row),
            },
        }
        enriched.append(ad)
    enriched.sort(
        key=lambda a: (a["_perf"]["results"], a["_perf"]["ctr"], a["_perf"]["impressions"]),
        reverse=True,
    )
    return enriched


async def fetch_adset_creatives(config: Any, adset_id: str, *, date_preset: str = "maximum") -> list[dict[str, Any]]:
    """Fetch ONE ad set's ads + lifetime ad-level insights and rank them."""
    from .meta_client import get_ads_for_adset, get_adset_ad_insights

    ads, insights = await asyncio.gather(
        get_ads_for_adset(config, adset_id),
        get_adset_ad_insights(config, adset_id, date_preset=date_preset),
    )
    return rank_creatives(ads, insights)


def fetch_adset_creatives_sync(adset_id: str) -> tuple[list[dict[str, Any]], str]:
    """Sync wrapper for the Telegram webhook. Falls back to the cached snapshot's ad
    list on error. Returns (ranked_ads, source)."""
    from .knowledge_base import load_knowledge_base
    from .meta_client import MetaApiError, get_meta_config

    config = get_meta_config()
    if config.is_configured:
        try:
            return asyncio.run(fetch_adset_creatives(config, adset_id)), "live"
        except MetaApiError:
            logger.exception("Scoped ad-set creatives fetch failed; falling back to snapshot")
        except Exception:
            logger.exception("Unexpected error fetching ad-set creatives")

    knowledge = load_knowledge_base() or {}
    ads = [a for a in (knowledge.get("raw", {}).get("ads", []) or []) if str(a.get("adset_id")) == str(adset_id)]
    return rank_creatives(ads, []), "snapshot"


def serialize_creative(ad: dict[str, Any]) -> dict[str, Any]:
    """Flatten a ranked ad into the JSON shape the web-app creatives view consumes."""
    creative = ad.get("creative") or {}
    perf = ad.get("_perf") or {}
    return {
        "id": str(ad.get("id") or ""),
        "name": ad.get("name"),
        "status": ad.get("effective_status") or ad.get("status"),
        "thumbnailUrl": creative.get("thumbnail_url"),
        "imageUrl": creative.get("image_url"),
        "title": creative.get("title"),
        "body": creative.get("body"),
        "videoId": creative.get("video_id"),
        "objectType": creative.get("object_type"),
        "perf": {
            "impressions": perf.get("impressions", 0),
            "clicks": perf.get("clicks", 0),
            "spend": perf.get("spend", 0.0),
            "ctr": perf.get("ctr", 0.0),
            "results": perf.get("results", 0),
            "resultsLabel": perf.get("results_label"),
            "hasData": perf.get("has_data", False),
        },
    }

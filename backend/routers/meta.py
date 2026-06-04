"""Meta Marketing API connection, sync, and knowledge-base routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from ..analysis_engine import build_meta_analysis
from ..api_models import MetaSyncRequest
from ..knowledge_base import load_knowledge_base, save_knowledge_base
from ..llm_reasoner import generate_llm_summary
from ..meta_client import (
    MetaApiError,
    get_ad_account_summary,
    get_ad_sets,
    get_ads,
    get_campaigns,
    get_meta_config,
    get_token_permissions,
    get_video_source,
    mask_token,
)
from ..meta_sync import normalize_sync_days, safe_chunked_insights, safe_list
from ..settings_audit import build_settings_audit
from ..snapshot_store import build_snapshot_payload, list_snapshots, save_snapshot

router = APIRouter()


@router.get("/api/meta/status")
async def meta_status() -> dict[str, Any]:
    config = get_meta_config()
    result: dict[str, Any] = {
        "configured": config.is_configured,
        "apiVersion": config.api_version,
        "appId": config.app_id,
        "adAccountId": config.ad_account_id,
        "businessId": config.business_id,
        "pixelConfigured": bool(config.pixel_id),
        "tokenConfigured": bool(config.access_token),
        "tokenPreview": mask_token(config.access_token),
        "liveWritesEnabled": os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true",
        "connected": False,
        "account": None,
        "error": None,
    }

    if not config.is_configured:
        result["error"] = "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env."
        return result

    try:
        result["account"] = await get_ad_account_summary(config)
        result["connected"] = True
    except MetaApiError as error:
        result["error"] = str(error)

    return result


@router.get("/api/meta/campaigns")
async def meta_campaigns() -> dict[str, Any]:
    config = get_meta_config()

    if not config.is_configured:
        return {
            "configured": False,
            "campaigns": [],
            "error": "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env.",
        }

    try:
        return {
            "configured": True,
            "campaigns": await get_campaigns(config),
            "error": None,
        }
    except MetaApiError as error:
        return {
            "configured": True,
            "campaigns": [],
            "error": str(error),
        }


@router.get("/api/meta/permissions")
async def meta_permissions() -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"configured": False, "permissions": [], "error": "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env."}
    try:
        return {"configured": True, "permissions": await get_token_permissions(config), "error": None}
    except MetaApiError as error:
        return {"configured": True, "permissions": [], "error": str(error)}


@router.get("/api/meta/video/{video_id}")
async def meta_video(video_id: str) -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "videoUrl": None, "posterUrl": None, "error": "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env."}

    try:
        payload = await get_video_source(config, video_id)
        thumbnails = payload.get("thumbnails", {}).get("data", [])
        poster = payload.get("picture") or (thumbnails[0].get("uri") if thumbnails else None)
        return {
            "ok": True,
            "videoUrl": payload.get("source"),
            "posterUrl": poster,
            "permalinkUrl": payload.get("permalink_url"),
            "error": None,
        }
    except MetaApiError as error:
        return {"ok": False, "videoUrl": None, "posterUrl": None, "error": str(error)}


@router.post("/api/meta/sync")
async def meta_sync(request: MetaSyncRequest | None = None) -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env."}

    days = normalize_sync_days(request.days if request else 90)

    try:
        raw = {
            "account": await get_ad_account_summary(config),
            "campaigns": await safe_list("campaigns", get_campaigns(config)),
            "adsets": await safe_list("adsets", get_ad_sets(config)),
            "ads": await safe_list("ads", get_ads(config)),
            "permissions": await safe_list("permissions", get_token_permissions(config)),
            "insights": {
                "base": await safe_chunked_insights(config, "insights_base", None, days=days),
                "age_gender": await safe_chunked_insights(config, "insights_age_gender", ["age", "gender"], days=days),
                "country": await safe_chunked_insights(config, "insights_country", ["country"], days=days),
                "region": await safe_chunked_insights(config, "insights_region", ["region"], days=days),
                "placement": await safe_chunked_insights(config, "insights_placement", ["publisher_platform", "platform_position"], days=days),
            },
        }
        analysis_preview = build_meta_analysis(raw)["analysis"]
        llm_summary = await generate_llm_summary({
            "summary": analysis_preview["summary"],
            "topCampaigns": analysis_preview["topCampaigns"][:5],
            "topAds": analysis_preview["topAds"][:5],
            "audience": {
                "ageGender": analysis_preview["audience"]["ageGender"][:8],
                "countries": analysis_preview["audience"]["countries"][:8],
                "regions": analysis_preview["audience"]["regions"][:8],
                "interests": analysis_preview["audience"]["interests"][:8],
            },
            "placements": analysis_preview["placements"][:8],
            "recommendations": analysis_preview["recommendations"],
            "lessons": analysis_preview["lessons"],
        })
        knowledge = build_meta_analysis(raw, llm_summary=llm_summary)
        snapshot = save_snapshot(build_snapshot_payload(
            raw=raw,
            analysis=knowledge["analysis"],
            account_id=config.ad_account_id,
            days=days,
        ))
        knowledge["snapshot"] = snapshot
        save_knowledge_base(knowledge)
        return {
            "ok": True,
            "snapshot": snapshot,
            "rawCounts": knowledge["analysis"]["rawCounts"],
            "summary": knowledge["analysis"]["summary"],
            "recommendations": knowledge["analysis"]["recommendations"],
            "llmEnabled": bool(llm_summary and not llm_summary.startswith("LLM summary unavailable")),
        }
    except MetaApiError as error:
        return {"ok": False, "error": str(error)}


@router.get("/api/meta/snapshots")
def meta_snapshots() -> dict[str, Any]:
    return {"snapshots": list_snapshots()}


@router.get("/api/meta/settings-audit")
def meta_settings_audit() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if not knowledge:
        return {"available": False, "error": "No Meta sync has been saved yet.", "audit": None}
    return {"available": True, "audit": build_settings_audit(knowledge.get("raw", {}))}


@router.get("/api/knowledge-base")
def knowledge_base() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if not knowledge:
        return {"available": False, "error": "No Meta sync has been saved yet."}
    return {"available": True, "knowledge": knowledge}

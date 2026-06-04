"""Dashboard data mapping and chat-answer helpers.

Transforms the saved Meta knowledge base into the dashboard payload and
produces the natural-language chat answers. Extracted from app.py so the web
entrypoint stays focused on routing; app.py re-imports the names it serves.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from .analysis_engine import action_count, action_value, as_float, extract_interests, ratio, valid_rows
from .campaign_watch import build_campaign_watch
from .knowledge_base import KNOWLEDGE_BASE_PATH, load_knowledge_base
from .meta_client import get_meta_config
from .monitoring_runner import ALERTS_PATH, list_monitoring_alerts
from .demo_dashboard import (
    ad_sets,
    ads,
    approval_actions,
    audience,
    campaigns,
    creative_analyses,
    creatives,
    experiments,
    glossary,
    insights,
    metrics,
    tracking_health,
)

DASHBOARD_CACHE: dict[str, Any] = {
    "key": None,
    "payload": None,
}
# FastAPI serves these handlers from a threadpool, so guard the shared cache to
# avoid a TOCTOU race where one request's payload overwrites/leaks into another's.
_CACHE_LOCK = threading.Lock()


def build_dashboard() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if knowledge:
        cache_key = dashboard_cache_key()
        with _CACHE_LOCK:
            if DASHBOARD_CACHE["key"] == cache_key and DASHBOARD_CACHE["payload"]:
                return DASHBOARD_CACHE["payload"]

        # Compute outside the lock (it can be expensive); each caller returns its own
        # freshly computed payload, so no request ever sees another's mid-flight object.
        payload = dashboard_from_knowledge_base(knowledge)
        with _CACHE_LOCK:
            DASHBOARD_CACHE["key"] = cache_key
            DASHBOARD_CACHE["payload"] = payload
        return payload

    return {
        "campaigns": campaigns,
        "adSets": ad_sets,
        "ads": ads,
        "creatives": creatives,
        "creativeAnalyses": creative_analyses,
        "metrics": metrics,
        "kpis": derive_kpis(metrics),
        "funnel": derive_funnel(metrics),
        "trend": derive_trend(metrics),
        "creativeScores": derive_creative_scores(metrics),
        "placements": derive_placements(metrics),
        "audience": audience,
        "insights": insights,
        "experiments": experiments,
        "trackingHealth": tracking_health,
        "monitoringAlerts": list_monitoring_alerts(),
        "campaignWatch": build_campaign_watch(
            {
                "campaigns": campaigns,
                "metrics": metrics,
            }
        ),
        "approvalActions": approval_actions,
        "glossary": glossary,
        "dataSource": {
            "kind": "mock",
            "label": "Mock dashboard model",
            "generatedAt": None,
            "syncErrors": [],
        },
    }


def dashboard_cache_key() -> tuple[int | None, int | None]:
    return (file_mtime_ns(KNOWLEDGE_BASE_PATH), file_mtime_ns(ALERTS_PATH))


def file_mtime_ns(path: Any) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None

def derive_kpis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spend = sum(row["spendUsd"] for row in rows)
    subs = sum(row["telegramSubscribers"] for row in rows)
    buyers = sum(row["purchases"] for row in rows)
    tracking = round(sum(item["matchRate"] for item in tracking_health) / len(tracking_health)) if tracking_health else 0
    return [
        {"label": "Spend", "value": money(spend), "change": f"{len(rows)} rows", "helper": "From backend API", "tone": "neutral", "icon": "dollar"},
        {"label": "Telegram Subs", "value": f"{subs:,}", "change": money(spend / subs) if subs else "$0", "helper": "Attributed subscriber volume", "tone": "good", "icon": "bot"},
        {"label": "Buyers", "value": f"{buyers:,}", "change": f"{money(spend / buyers)} CPA" if buyers else "No buyers", "helper": "Course purchases", "tone": "good" if buyers else "warning", "icon": "users"},
        {"label": "Tracking Health", "value": f"{tracking}%", "change": "Stable", "helper": "Average source match rate", "tone": "good", "icon": "check"},
    ]


def dashboard_from_knowledge_base(knowledge: dict[str, Any]) -> dict[str, Any]:
    raw = knowledge.get("raw", {})
    analysis = knowledge.get("analysis", {})
    snapshot = knowledge.get("snapshot", {})
    raw_campaigns = valid_rows(raw.get("campaigns", []))
    raw_adsets = valid_rows(raw.get("adsets", []))
    raw_ads = valid_rows(raw.get("ads", []))
    metric_rows = (
        valid_rows(raw.get("insights", {}).get("base", []))
        or valid_rows(raw.get("insights", {}).get("age_gender", []))
        or valid_rows(raw.get("insights", {}).get("placement", []))
    )

    campaigns_real = [map_campaign(row) for row in raw_campaigns[:100]]
    adsets_real = [map_adset(row) for row in raw_adsets[:150]]
    analyses_real = build_creative_analyses(analysis)
    enrich_metric_rows_with_ads(metric_rows, raw_ads)
    metrics_real = [map_metric_row(row, index) for index, row in enumerate(metric_rows)]
    ads_real = complete_ads([map_ad(row) for row in raw_ads], metrics_real)
    creatives_real = complete_creatives([map_creative(row) for row in raw_ads], metrics_real, analysis)
    audience_real = build_audience_scores(analysis)
    insights_real = build_dashboard_insights(analysis)
    experiments_real = build_dashboard_experiments(analysis)
    tracking_real = build_tracking_health(analysis)
    actions_real = build_approval_actions(analysis)

    return {
        "campaigns": campaigns_real or campaigns,
        "adSets": adsets_real or ad_sets,
        "ads": ads_real or ads,
        "creatives": creatives_real or creatives,
        "creativeAnalyses": analyses_real or creative_analyses,
        "metrics": metrics_real or metrics,
        "kpis": derive_real_kpis(analysis),
        "funnel": derive_funnel(metrics_real or metrics),
        "trend": derive_trend(metrics_real or metrics),
        "creativeScores": derive_creative_scores(metrics_real or metrics),
        "placements": build_placement_scores(analysis) or derive_placements(metrics_real or metrics),
        "audience": audience_real or audience,
        "insights": insights_real,
        "experiments": experiments_real,
        "trackingHealth": tracking_real,
        "monitoringAlerts": list_monitoring_alerts(),
        "campaignWatch": build_campaign_watch(
            {
                "campaigns": campaigns_real or campaigns,
                "metrics": metrics_real or metrics,
            }
        ),
        "approvalActions": actions_real,
        "glossary": glossary,
        "dataSource": {
            "kind": "meta",
            "label": f"Real Meta {snapshot.get('days') or 90}-day analysis",
            "generatedAt": analysis.get("generatedAt"),
            "snapshotId": snapshot.get("id"),
            "days": snapshot.get("days") or 90,
            "rawCounts": analysis.get("rawCounts", {}),
            "syncErrors": analysis.get("syncErrors", []),
        },
    }


def map_campaign(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "platform": "meta",
        "name": row.get("name") or "Untitled campaign",
        "objective": map_objective(row.get("objective")),
        "status": map_status(row.get("effective_status") or row.get("status")),
        # Meta returns budgets in minor account-currency units (cents); convert to USD.
        "dailyBudgetUsd": as_float(row.get("daily_budget")) / 100,
        "startedAt": date_part(row.get("start_time")),
        "endedAt": date_part(row.get("stop_time") or row.get("end_time")),
    }


def map_adset(row: dict[str, Any]) -> dict[str, Any]:
    targeting = row.get("targeting") or {}
    geo = targeting.get("geo_locations") or {}
    return {
        "id": str(row.get("id")),
        "campaignId": str(row.get("campaign_id") or ""),
        "name": row.get("name") or "Untitled ad set",
        "status": map_status(row.get("effective_status") or row.get("status")),
        "ageMin": int(as_float(targeting.get("age_min") or 18)),
        "ageMax": int(as_float(targeting.get("age_max") or 65)),
        "genders": ["all"],
        "locations": geo.get("countries") or ["Unknown"],
        "interests": extract_interests(targeting) or ["Broad / Advantage audience"],
        "placements": ["instagram_reels", "instagram_stories", "instagram_feed", "facebook_feed", "facebook_reels"],
        "optimizationGoal": map_optimization(row.get("optimization_goal")),
    }


def map_ad(row: dict[str, Any]) -> dict[str, Any]:
    creative = row.get("creative") or {}
    return {
        "id": str(row.get("id")),
        "adSetId": str(row.get("adset_id") or ""),
        "creativeId": creative_id_for_ad(row.get("id"), creative.get("id")),
        "name": row.get("name") or "Untitled ad",
        "status": map_status(row.get("effective_status") or row.get("status")),
    }


def map_creative(row: dict[str, Any]) -> dict[str, Any]:
    creative = row.get("creative") or {}
    creative_id = creative_id_for_ad(row.get("id"), creative.get("id"))
    name = creative.get("title") or creative.get("name") or row.get("name") or "Untitled creative"
    return {
        "id": creative_id,
        "adId": str(row.get("id")),
        "campaignId": str(row.get("campaign_id") or ""),
        "adSetId": str(row.get("adset_id") or ""),
        "name": short_text(name, 82),
        "format": "video" if creative.get("video_id") or "VID" in str(row.get("name", "")).upper() else "image",
        "theme": infer_theme(name, creative.get("body")),
        "hookType": infer_hook(name, creative.get("body")),
        "primaryPersona": "AI course prospect",
        "cta": "Join / watch VSL / register",
        "assetUrl": creative.get("thumbnail_url"),
        "videoId": creative.get("video_id"),
        "videoUrl": creative.get("video_url"),
    }


def map_metric_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    clicks = as_float(row.get("clicks"))
    link_clicks = action_count(row, "link_click")
    landing_visits = action_count(row, "landing_visit")
    leads = action_count(row, "lead") + action_count(row, "registration")
    purchases = action_count(row, "purchase")
    revenue = action_value(row, "purchase")
    ad_id = str(row.get("ad_id") or f"unknown_ad_{index}")
    creative_id = row.get("creative_id") or (row.get("creative") or {}).get("id")
    return {
        "date": row.get("date_start") or row.get("date_stop") or "2026-01-01",
        "campaignId": str(row.get("campaign_id") or ""),
        "adSetId": str(row.get("adset_id") or ""),
        "adId": ad_id,
        "creativeId": creative_id_for_ad(ad_id, creative_id),
        "placement": normalize_placement(row),
        "spendUsd": as_float(row.get("spend")),
        "impressions": int(as_float(row.get("impressions"))),
        "clicks": int(clicks),
        "landingPageViews": int(landing_visits or link_clicks or clicks),
        "leads": int(leads),
        "telegramSubscribers": 0,
        "webinarAttendees": 0,
        "purchases": int(purchases),
        "purchaseRevenueUsd": round(revenue, 2),
    }


def enrich_metric_rows_with_ads(metric_rows: list[dict[str, Any]], raw_ads: list[dict[str, Any]]) -> None:
    ad_lookup = {str(ad.get("id")): ad for ad in raw_ads if ad.get("id")}
    for row in metric_rows:
        ad = ad_lookup.get(str(row.get("ad_id")))
        if not ad:
            continue
        creative = ad.get("creative") or {}
        row["creative_id"] = creative.get("id") or row.get("creative_id")


def build_creative_analyses(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for ad in analysis.get("topAds", [])[:30]:
        ad_id = str(ad.get("keys", {}).get("ad_id") or ad.get("label"))
        quality = int(round(ad.get("qualityScore", 0)))
        lead_rate = ad.get("leadRateFromClick", 0)
        purchases = ad.get("purchases", 0)
        items.append({
            "creativeId": creative_id_for_ad(ad_id),
            "viralScore": clamp_score(ad.get("ctr", 0) * 10),
            "buyerIntentScore": clamp_score(quality + (20 if purchases else 0)),
            "courseFitScore": clamp_score(55 + min(30, lead_rate / 2)),
            "purchasingPowerScore": clamp_score(35 + (25 if purchases else 0)),
            "funnelQualityScore": clamp_score(quality),
            "hookSummary": f"{ad.get('label', 'Creative')} generated {ad.get('clicks', 0):,.0f} clicks and {ad.get('leads', 0):,.0f} leads.",
            "conversionRisk": "Purchase tracking is missing or shows zero purchases, so buyer quality is not proven yet.",
            "recommendedAction": "Review and test",
            "sceneNotes": [
                "Use video analysis next to explain the visual hook, pacing, and offer clarity.",
                "Compare this creative against downstream lead quality, not CTR alone.",
                "Track Telegram, webinar, and purchase events before scaling aggressively.",
            ],
            "whyItWorked": "It earned measurable attention and lead activity in the saved Meta data.",
            "whyItDidNotConvert": "The account has no attributed purchases in the saved analysis, so conversion proof is currently incomplete.",
        })
    return items


def complete_ads(existing_ads: list[dict[str, Any]], metrics_real: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ads_by_id = {ad["id"]: ad for ad in existing_ads}
    for metric in metrics_real:
        ad_id = metric["adId"]
        if ad_id not in ads_by_id:
            ads_by_id[ad_id] = {
                "id": ad_id,
                "adSetId": metric["adSetId"],
                "creativeId": metric["creativeId"],
                "name": f"Ad {ad_id}",
                "status": "completed",
            }
    return list(ads_by_id.values())


def complete_creatives(
    existing_creatives: list[dict[str, Any]],
    metrics_real: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    creatives_by_id = {creative["id"]: creative for creative in existing_creatives}
    top_ads_by_id = {
        str(item.get("keys", {}).get("ad_id")): item
        for item in analysis.get("topAds", [])
        if item.get("keys", {}).get("ad_id")
    }
    names_by_ad_id: dict[str, str] = {}
    for metric in metrics_real:
        names_by_ad_id.setdefault(metric["adId"], metric["adId"])

    for metric in metrics_real:
        creative_id = metric["creativeId"]
        if creative_id in creatives_by_id:
            continue

        ad_id = metric["adId"]
        top_ad = top_ads_by_id.get(ad_id, {})
        ad_name = top_ad.get("keys", {}).get("ad_name") or names_by_ad_id.get(ad_id) or f"Ad {ad_id}"
        creatives_by_id[creative_id] = {
            "id": creative_id,
            "adId": ad_id,
            "name": short_text(ad_name, 82),
            "format": "video" if "VID" in str(ad_name).upper() else "image",
            "theme": "Meta synced creative",
            "hookType": "Needs video analysis",
            "primaryPersona": "AI course prospect",
            "cta": "Review creative metadata",
            "assetUrl": None,
        }

    return list(creatives_by_id.values())


def build_audience_scores(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    age_gender = analysis.get("audience", {}).get("ageGender", [])[:10]
    return [
        {
            "segment": item.get("label", "Unknown"),
            "spend": round(item.get("spend", 0), 2),
            "subs": int(item.get("leads", 0)),
            "buyers": int(item.get("purchases", 0)),
        }
        for item in age_gender
    ]


def build_placement_scores(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    placements = analysis.get("placements", [])
    total_spend = sum(item.get("spend", 0) for item in placements)
    return [
        {
            "name": friendly_placement_name(item.get("label", "Unknown")),
            "value": round((item.get("spend", 0) / total_spend) * 100) if total_spend else 0,
            "buyers": int(item.get("purchases", 0)),
        }
        for item in placements[:8]
    ]


def build_dashboard_insights(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    summary = analysis.get("summary", {})
    insights_real = [
        {
            "icon": "trendingDown",
            "title": "Purchase proof is missing",
            "body": f"{summary.get('leads', 0):,.0f} leads are visible, but purchases are {summary.get('purchases', 0):,.0f}. Treat lead quality as a proxy until Pixel/CAPI and sales attribution are confirmed.",
            "tone": "warning",
        },
    ]
    for recommendation in analysis.get("recommendations", [])[:3]:
        insights_real.append({
            "icon": "target",
            "title": recommendation.get("title", "Recommendation"),
            "body": recommendation.get("reason", ""),
            "tone": "good",
        })
    for error in analysis.get("syncErrors", [])[:1]:
        insights_real.append({
            "icon": "alert",
            "title": f"Sync limit: {error.get('source', 'Meta API')}",
            "body": "Some Meta insight rows need smaller-window retries before the dashboard can be fully complete.",
            "tone": "warning",
        })
    return insights_real[:5]


def build_dashboard_experiments(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    recs = analysis.get("recommendations", [])
    experiments_real = [
        {
            "title": rec.get("title", "Controlled Meta test"),
            "metric": "Qualified lead quality first; purchases once tracking is confirmed",
            "budget": "Small controlled test for 3 days before scaling",
        }
        for rec in recs[:4]
    ]
    if not experiments_real:
        experiments_real.append({
            "title": "Fix purchase and Telegram attribution before scale",
            "metric": "Every lead has campaign, ad set, ad, creative, Telegram, webinar, and purchase state",
            "budget": "No budget increase until tracking is verified",
        })
    return experiments_real


def build_tracking_health(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    generated = analysis.get("generatedAt", "Unknown")
    purchases = analysis.get("summary", {}).get("purchases", 0)
    errors = analysis.get("syncErrors", [])
    config = get_meta_config()
    return [
        {
            "name": "Meta Marketing API",
            "status": "warning" if errors else "healthy",
            "matchRate": 72 if errors else 92,
            "lastEventAt": generated,
            "note": "Read connection works; some insight breakdowns may need smaller-window retries." if errors else "Read connection and insight sync are healthy.",
        },
        {
            "name": "Meta Pixel",
            "status": "healthy" if config.pixel_id else "warning",
            "matchRate": 85 if config.pixel_id else 25,
            "lastEventAt": generated if config.pixel_id else "Not configured",
            "note": "Pixel ID is configured locally; next step is verifying PageView, Lead, and Purchase events." if config.pixel_id else "No META_PIXEL_ID is set yet. Landing visits are currently estimated from landing-page-view/link-click signals.",
        },
        {
            "name": "Purchase Events",
            "status": "warning" if not purchases else "healthy",
            "matchRate": 35 if not purchases else 88,
            "lastEventAt": generated,
            "note": "No attributed purchases in the saved Meta analysis. Verify Pixel/CAPI, checkout, and offline/course sales import.",
        },
        {
            "name": "Telegram Bot Start",
            "status": "warning",
            "matchRate": 20,
            "lastEventAt": "Not connected",
            "note": "Telegram subscriber and warm-up events are not connected to this dashboard yet.",
        },
        {
            "name": "Webinar Attendance",
            "status": "warning",
            "matchRate": 20,
            "lastEventAt": "Not connected",
            "note": "Webinar attendance/import data is needed for true lead quality scoring.",
        },
    ]


def build_approval_actions(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for index, rec in enumerate(analysis.get("recommendations", [])[:4]):
        actions.append({
            "id": f"meta_rec_{index}",
            "title": rec.get("title", "Review recommendation"),
            "impact": rec.get("reason", "Improve campaign quality."),
            "risk": "medium",
            "owner": "human",
            "status": "needs_review",
        })
    actions.append({
        "id": "fix_purchase_attribution",
        "title": "Verify purchase, Telegram, and webinar tracking",
        "impact": "Turns the dashboard from lead-quality analysis into buyer-quality analysis.",
        "risk": "high",
        "owner": "human",
        "status": "needs_review",
    })
    return actions


def derive_real_kpis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    summary = analysis.get("summary", {})
    spend = summary.get("spend", 0)
    leads = summary.get("leads", 0)
    purchases = summary.get("purchases", 0)
    revenue = summary.get("revenue", 0)
    roas = summary.get("roas", 0) or ratio(revenue, spend)
    # ROAS/MER is the #1 media-buying KPI. When no purchase revenue is attributed we
    # say so explicitly rather than implying a real return exists.
    if revenue > 0:
        roas_card = {
            "label": "ROAS",
            "value": f"{roas:.2f}x",
            "change": f"{money(revenue)} revenue",
            "helper": f"Blended MER on {money(spend)} spend",
            "tone": "good" if roas >= 1 else "danger",
            "icon": "trendingUp",
        }
    else:
        roas_card = {
            "label": "ROAS",
            "value": "No revenue",
            "change": "Lead-quality only",
            "helper": "No purchase revenue attributed — connect purchase tracking",
            "tone": "warning",
            "icon": "trendingUp",
        }
    return [
        {"label": "Meta Spend", "value": money(spend), "change": f"{summary.get('clicks', 0):,.0f} clicks", "helper": "Real synced Meta data", "tone": "neutral", "icon": "dollar"},
        roas_card,
        {"label": "Leads", "value": f"{leads:,.0f}", "change": f"{money(summary.get('cpl', 0))} CPL", "helper": "Meta lead/registration events", "tone": "good" if leads else "warning", "icon": "users"},
        {"label": "Purchases", "value": f"{purchases:,.0f}", "change": "Tracking gap" if not purchases else f"{money(summary.get('cpp', 0))} CPP", "helper": "Attributed purchases", "tone": "warning" if not purchases else "good", "icon": "target"},
        {"label": "Quality Score", "value": f"{summary.get('qualityScore', 0):.1f}", "change": f"{summary.get('ctr', 0):.2f}% CTR", "helper": "Lead/click quality proxy", "tone": "warning", "icon": "check"},
    ]


def creative_id_for_ad(ad_id: Any, creative_id: Any = None) -> str:
    if creative_id:
        return str(creative_id)
    return f"creative_{ad_id}"


def map_objective(value: Any) -> str:
    text = str(value or "").lower()
    if "sales" in text:
        return "sales"
    if "lead" in text:
        return "leads"
    if "traffic" in text:
        return "traffic"
    if "engagement" in text:
        return "engagement"
    return "awareness"


def map_optimization(value: Any) -> str:
    text = str(value or "").lower()
    if "purchase" in text:
        return "purchase"
    if "conversion" in text or "offsite" in text:
        return "conversion"
    if "landing" in text:
        return "landing_page_view"
    return "lead"


def map_status(value: Any) -> str:
    text = str(value or "").upper()
    if "ACTIVE" in text and "PAUSED" not in text:
        return "active"
    if "PAUSED" in text:
        return "paused"
    return "completed"


def normalize_placement(row: dict[str, Any]) -> str:
    platform = str(row.get("publisher_platform") or "").lower()
    position = str(row.get("platform_position") or "").lower()
    if platform == "instagram" and "story" in position:
        return "instagram_stories"
    if platform == "instagram" and "reel" in position:
        return "instagram_reels"
    if platform == "instagram":
        return "instagram_feed"
    if platform == "facebook" and "reel" in position:
        return "facebook_reels"
    if platform == "audience_network":
        return "audience_network"
    if platform == "messenger":
        return "messenger"
    return "facebook_feed"


def friendly_placement_name(value: Any) -> str:
    text = str(value or "Unknown")
    replacements = {
        "instagram / feed": "IG Feed",
        "instagram / instagram_stories": "IG Stories",
        "instagram / instagram_reels": "IG Reels",
        "facebook / facebook_reels": "FB Reels",
        "facebook / feed": "FB Feed",
        "audience_network": "Audience Network",
        "messenger": "Messenger",
        "threads / threads_feed": "Threads Feed",
    }
    return replacements.get(text, text.replace("_", " ").replace(" / ", " / ").title())


def date_part(value: Any) -> str:
    if not value:
        return ""
    return str(value)[:10]


def short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}..."


def infer_theme(name: Any, body: Any) -> str:
    text = f"{name or ''} {body or ''}".lower()
    if "bepul" in text or "free" in text:
        return "Free VSL / lead magnet"
    if "daromad" in text or "income" in text:
        return "AI income promise"
    if "webinar" in text:
        return "Webinar registration"
    return "Creative test"


def infer_hook(name: Any, body: Any) -> str:
    text = f"{name or ''} {body or ''}".lower()
    if "daromad" in text or "income" in text:
        return "Outcome / income hook"
    if "ai" in text or "sun" in text:
        return "AI opportunity hook"
    return "Attention hook"


def clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def answer_meta_status(meta: dict[str, Any]) -> str:
    if meta.get("connected"):
        account = meta.get("account") or {}
        return (
            f"Meta is connected to {account.get('name', 'your ad account')} "
            f"({meta.get('adAccountId')}). Currency is {account.get('currency', 'unknown')} "
            f"and timezone is {account.get('timezone_name', 'unknown')}. The next step is to sync campaigns, "
            "ad sets, ads, creatives, and insights into the dashboard model."
        )
    return f"Meta is not fully connected yet. Current issue: {meta.get('error') or 'unknown error'}"


def answer_from_knowledge_base(lower_question: str, knowledge: dict[str, Any]) -> str | None:
    analysis = knowledge.get("analysis", {})
    if not analysis:
        return None

    min_spend = max(5, analysis.get("summary", {}).get("spend", 0) * 0.02)

    if any(word in lower_question for word in ["country", "region", "city", "geo", "location"]):
        country = first_eligible_answer(analysis.get("audience", {}).get("countries", []), min_spend)
        region = first_eligible_answer(analysis.get("audience", {}).get("regions", []), min_spend)
        return (
            f"For geo targeting, start at country level unless a region clearly beats the account average with enough spend. "
            f"Best country in the saved analysis: {country['label'] if country else 'not enough country data'}. "
            f"Best region with meaningful spend: {region['label'] if region else 'not enough region data'}. "
            "Country targeting gives Meta more learning room; region targeting is useful after a region repeatedly proves better CPL/CPA."
        )

    if any(word in lower_question for word in ["age", "gender", "male", "female", "audience", "target", "interest", "ad set", "adset"]):
        return answer_audiences_from_knowledge_base(knowledge)

    if any(word in lower_question for word in ["placement", "facebook", "instagram", "reels", "feed"]):
        return answer_placements_from_knowledge_base(knowledge)

    if any(word in lower_question for word in ["creative", "video", "hook", "thumbnail", "viral", "worked", "didn't", "did not"]):
        return answer_creatives_from_knowledge_base(knowledge)

    if any(word in lower_question for word in ["funnel", "telegram", "landing", "lead rate", "visit", "leak", "crm", "bot"]):
        return answer_funnel_from_knowledge_base(knowledge)

    if any(word in lower_question for word in ["summary", "learn", "lesson", "analysis", "recommend"]):
        llm = analysis.get("llmSummary")
        if llm:
            return llm
        recs = analysis.get("recommendations", [])
        lessons = analysis.get("lessons", [])
        return " ".join(
            [f"{item['area']}: {item['title']} Reason: {item['reason']}" for item in recs[:4]]
            + lessons[:3]
        )

    return None


def knowledge_chat_preview(knowledge: dict[str, Any]) -> dict[str, Any]:
    analysis = knowledge.get("analysis", {})
    summary = analysis.get("summary", {})
    tracking = tracking_calculations_from_knowledge(knowledge)
    days = knowledge.get("snapshot", {}).get("days") or 90
    return {
        "role": "canonical_meta_ads_knowledge_base",
        "analysisWindowDays": days,
        "instructions": [
            f"Use this {days}-day analysis as the source of truth for the user's Meta ads account.",
            "Reason across campaigns, ad sets, ads, audiences, placements, geos, interests, and funnel metrics.",
            "When asked how a metric is calculated, show the formula and plug in the actual saved numbers.",
            "Do not say there is not enough age/gender spend merely because a global minimum spend threshold is high; compare meaningful segments and state limitations.",
            "Purchases are currently zero, so buyer recommendations must be framed as lead/click-quality hypotheses until purchase, Telegram, and webinar tracking are connected.",
        ],
        "metricDefinitions": {
            "ctrPercent": "clicks / impressions * 100",
            "cpc": "spend / clicks",
            "cpl": "spend / leads",
            "leadRateFromClickPercent": "leads / clicks * 100",
            "purchaseRateFromClickPercent": "purchases / clicks * 100",
            "visitRatePercent": "landing page visits / clicks * 100",
            "landingPageLeadRatePercent": "leads / landing page visits * 100",
            "qualityScore": "internal proxy combining lead rate, purchase rate, and CTR; purchases have zero contribution while purchase tracking is missing",
        },
        "calculatedAccountMetrics": {
            "leadRateFromClickPercent": summary.get("leadRateFromClick"),
            "ctrPercent": summary.get("ctr"),
            "cpc": summary.get("cpc"),
            "cpl": summary.get("cpl"),
            "purchaseRateFromClickPercent": summary.get("purchaseRateFromClick"),
            "visitRatePercent": tracking["visitRatePercent"],
            "landingPageLeadRatePercent": tracking["landingPageLeadRatePercent"],
        },
        "tracking": tracking,
        "summary": analysis.get("summary", {}),
        "rawCounts": analysis.get("rawCounts", {}),
        "topCampaigns": analysis.get("topCampaigns", [])[:20],
        "topAds": analysis.get("topAds", [])[:30],
        "audience": {
            "ageGender": analysis.get("audience", {}).get("ageGender", [])[:30],
            "countries": analysis.get("audience", {}).get("countries", [])[:20],
            "regions": analysis.get("audience", {}).get("regions", [])[:30],
            "interests": analysis.get("audience", {}).get("interests", [])[:30],
        },
        "placements": analysis.get("placements", [])[:30],
        "recommendations": analysis.get("recommendations", [])[:15],
        "lessons": analysis.get("lessons", [])[:15],
        "llmSummary": analysis.get("llmSummary"),
        "syncErrors": analysis.get("syncErrors", [])[:5],
    }


def tracking_calculations_from_knowledge(knowledge: dict[str, Any]) -> dict[str, Any]:
    raw = knowledge.get("raw", {})
    rows = (
        valid_rows(raw.get("insights", {}).get("base", []))
        or valid_rows(raw.get("insights", {}).get("age_gender", []))
        or valid_rows(raw.get("insights", {}).get("placement", []))
    )
    clicks = sum(as_float(row.get("clicks")) for row in rows)
    link_clicks = sum(action_count(row, "link_click") for row in rows)
    pixel_landing_visits = sum(action_count(row, "landing_visit") for row in rows)
    estimated_landing_visits = pixel_landing_visits or link_clicks or clicks
    leads = sum(action_count(row, "lead") + action_count(row, "registration") for row in rows)
    purchases = sum(action_count(row, "purchase") for row in rows)
    config = get_meta_config()
    return {
        "pixelConfigured": bool(config.pixel_id),
        "pixelIdConfiguredLocally": bool(config.pixel_id),
        "landingVisitsSource": "Meta Pixel landing_page_view event" if pixel_landing_visits else "estimated from link_clicks/clicks until Pixel landing-page events are connected",
        "clicks": clicks,
        "linkClicks": link_clicks,
        "pixelLandingPageViews": pixel_landing_visits,
        "estimatedLandingPageVisits": estimated_landing_visits,
        "leads": leads,
        "purchases": purchases,
        "visitRatePercent": ratio_percent(estimated_landing_visits, clicks),
        "landingPageLeadRatePercent": ratio_percent(leads, estimated_landing_visits),
        "purchaseRateFromLandingVisitPercent": ratio_percent(purchases, estimated_landing_visits),
    }


def ratio_percent(value: float, base: float) -> float:
    return 0 if not base else (value / base) * 100


def answer_creatives(data: dict[str, Any]) -> str:
    scores = sorted(data["creativeScores"], key=lambda item: item["quality"], reverse=True)
    best = scores[0]
    weakest_intent = min(scores, key=lambda item: item["intent"])
    analysis = next(item for item in data["creativeAnalyses"] if item["creativeId"] == weakest_intent["id"])
    return (
        f"Best quality creative right now is {best['name']} with quality {best['quality']}, "
        f"buyer intent {best['intent']}, and {best['buyers']} buyers. "
        f"The risky creative is {weakest_intent['name']}: it has viral score {weakest_intent['viral']} "
        f"but buyer intent only {weakest_intent['intent']}. Why: {analysis['whyItDidNotConvert']} "
        f"Recommendation: {analysis['recommendedAction'].lower()} and make the course value clear earlier."
    )


def answer_audiences(data: dict[str, Any]) -> str:
    ranked = sorted(
        data["audience"],
        key=lambda item: item["buyers"] / max(1, item["subs"]),
        reverse=True,
    )
    best = ranked[0]
    weakest = ranked[-1]
    return (
        f"The strongest audience is {best['segment']}: {best['buyers']} buyers from {best['subs']} Telegram subs. "
        f"The weakest buying audience is {weakest['segment']}: {weakest['buyers']} buyers from {weakest['subs']} subs. "
        "I would shift testing toward the higher-buyer segment and use proof/course-value creatives rather than pure viral humor."
    )


def answer_placements(data: dict[str, Any]) -> str:
    placements_sorted = sorted(data["placements"], key=lambda item: item["buyers"], reverse=True)
    best = placements_sorted[0]
    spend_heavy_low_buyer = sorted(data["placements"], key=lambda item: (item["value"], -item["buyers"]), reverse=True)[0]
    return (
        f"The best buyer placement in the current model is {best['name']} with {best['buyers']} buyers. "
        f"Watch {spend_heavy_low_buyer['name']}: it has {spend_heavy_low_buyer['value']}% spend share "
        f"and {spend_heavy_low_buyer['buyers']} buyers. If this pattern holds with real Meta data, keep weak placements for retargeting only."
    )


def answer_funnel(data: dict[str, Any]) -> str:
    funnel_steps = data["funnel"][1:]
    weakest = min(funnel_steps, key=lambda item: parse_percent(item["rate"]))
    warning_tracking = [item for item in data["trackingHealth"] if item["status"] != "healthy"]
    warning_text = " ".join(f"{item['name']} is {item['status']} at {item['matchRate']}% match." for item in warning_tracking)
    return (
        f"The weakest funnel step is {weakest['step']} at {weakest['rate']}. "
        f"That is the first place I would diagnose before scaling spend. "
        f"Watch landing visit rate, landing lead rate, Telegram START rate, and CRM quality together. {warning_text}"
    )


def answer_experiments(data: dict[str, Any]) -> str:
    first = data["experiments"][0]
    ready_actions = [item for item in data["approvalActions"] if item["status"] == "ready"]
    actions = ", ".join(item["title"] for item in ready_actions[:2])
    return (
        f"First experiment: {first['title']}. Success metric: {first['metric']}. Budget: {first['budget']}. "
        f"Ready actions in the queue: {actions or 'none yet'}. I would avoid broad budget increases until real Meta insights are synced."
    )


def answer_summary(data: dict[str, Any], meta: dict[str, Any]) -> str:
    spend = sum(row["spendUsd"] for row in data["metrics"])
    buyers = sum(row["purchases"] for row in data["metrics"])
    connected = "connected" if meta.get("connected") else "not connected"
    return (
        f"Meta is {connected}. The current dashboard model shows {money(spend)} spend and {buyers} buyers. "
        "Main pattern: proof-led creatives and older buyer-intent audiences look healthier than viral humor traffic. "
        "Ask me about creatives, audiences, placements, funnel leaks, or experiments."
    )


def default_questions() -> list[str]:
    return [
        "Which creative should we scale?",
        "Where is the biggest funnel leak?",
        "What experiment should we run first?",
    ]


def first(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[0] if items else None


def first_playbook_with_segments(playbooks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for playbook in playbooks:
        if playbook.get("segments"):
            return playbook
    return None


def last(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return items[-1] if items else None


def first_eligible_answer(items: list[dict[str, Any]], min_spend: float) -> dict[str, Any] | None:
    for item in items:
        if item.get("spend", 0) >= min_spend:
            return item
    return None


def parse_percent(value: str) -> float:
    try:
        return float(value.replace("%", ""))
    except ValueError:
        return 0


def derive_funnel(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = {
        "impressions": sum(row["impressions"] for row in rows),
        "clicks": sum(row["clicks"] for row in rows),
        "landingPageViews": sum(row["landingPageViews"] for row in rows),
        "leads": sum(row["leads"] for row in rows),
        "telegramSubscribers": sum(row["telegramSubscribers"] for row in rows),
        "webinarAttendees": sum(row["webinarAttendees"] for row in rows),
        "purchases": sum(row["purchases"] for row in rows),
    }
    return [
        {"step": "Ad impressions", "value": totals["impressions"], "rate": "100%"},
        {"step": "Clicks", "value": totals["clicks"], "rate": pct(totals["clicks"], totals["impressions"])},
        {"step": "Landing visits", "value": totals["landingPageViews"], "rate": pct(totals["landingPageViews"], totals["clicks"])},
        {"step": "Leads", "value": totals["leads"], "rate": pct(totals["leads"], totals["landingPageViews"])},
        {"step": "Telegram subs", "value": totals["telegramSubscribers"], "rate": pct(totals["telegramSubscribers"], totals["leads"])},
        {"step": "Webinar attendees", "value": totals["webinarAttendees"], "rate": pct(totals["webinarAttendees"], totals["telegramSubscribers"])},
        {"step": "Buyers", "value": totals["purchases"], "rate": pct(totals["purchases"], totals["webinarAttendees"])},
    ]


def derive_trend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = grouped.setdefault(row["date"], {"day": format_day(row["date"]), "spend": 0, "leads": 0, "buyers": 0})
        current["spend"] += row["spendUsd"]
        current["leads"] += row["leads"]
        current["buyers"] += row["purchases"]
    return [grouped[key] for key in sorted(grouped)]


def derive_creative_scores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scores = []
    for creative in creatives:
        creative_rows = [row for row in rows if row["creativeId"] == creative["id"]]
        analysis = next(item for item in creative_analyses if item["creativeId"] == creative["id"])
        quality = round(
            (
                analysis["buyerIntentScore"]
                + analysis["courseFitScore"]
                + analysis["purchasingPowerScore"]
                + analysis["funnelQualityScore"]
            )
            / 4
        )
        scores.append(
            {
                "id": creative["id"],
                "name": creative["name"],
                "type": creative["theme"],
                "format": creative["format"],
                "clicks": sum(row["clicks"] for row in creative_rows),
                "leads": sum(row["leads"] for row in creative_rows),
                "buyers": sum(row["purchases"] for row in creative_rows),
                "viral": analysis["viralScore"],
                "intent": analysis["buyerIntentScore"],
                "courseFit": analysis["courseFitScore"],
                "quality": quality,
                "action": analysis["recommendedAction"],
                "tone": "good" if analysis["buyerIntentScore"] >= 70 else "warning" if analysis["buyerIntentScore"] >= 45 else "danger",
            }
        )
    return scores


def derive_placements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "instagram_reels": "IG Reels",
        "instagram_stories": "IG Stories",
        "instagram_feed": "IG Feed",
        "facebook_feed": "FB Feed",
        "facebook_reels": "FB Reels",
        "audience_network": "Audience Network",
        "messenger": "Messenger",
    }
    spend_total = sum(row["spendUsd"] for row in rows)
    grouped: defaultdict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0, "buyers": 0})
    for row in rows:
        grouped[row["placement"]]["spend"] += row["spendUsd"]
        grouped[row["placement"]]["buyers"] += row["purchases"]
    return [
        {
            "name": labels[placement],
            "value": round((values["spend"] / spend_total) * 100) if spend_total else 0,
            "buyers": values["buyers"],
        }
        for placement, values in grouped.items()
    ]


def pct(value: int | float, previous: int | float) -> str:
    return "0%" if previous == 0 else f"{(value / previous) * 100:.1f}%"


def money(value: float) -> str:
    return f"${value:,.0f}" if value >= 100 else f"${value:,.2f}"


def format_day(value: str) -> str:
    return datetime.fromisoformat(value).strftime("%b %#d")


# --- Knowledge-base-driven specialist answers (merged from codex/meta-agent) ---
# Rank ad sets / placements / creatives and diagnose the funnel directly from the
# saved 180-day Meta knowledge base, with Uzbekistan purchasing-power framing.

def answer_audiences_from_knowledge_base(knowledge: dict[str, Any]) -> str:
    analysis = knowledge.get("analysis", {})
    audience = analysis.get("audience", {})
    min_spend = max(5, analysis.get("summary", {}).get("spend", 0) * 0.02)
    raw_rows = valid_rows(knowledge.get("raw", {}).get("insights", {}).get("base", []))
    adset_rankings = rank_raw_insight_rows(raw_rows, ["adset_id", "adset_name"])
    meaningful_adsets = [item for item in adset_rankings if has_meaningful_audience_evidence(item, min_spend)]
    top_adsets = meaningful_adsets[:5]
    meaningful_interests = [item for item in audience.get("interests", []) if has_meaningful_audience_evidence(item, min_spend)]
    meaningful_age_gender = [item for item in audience.get("ageGender", []) if has_meaningful_audience_evidence(item, min_spend)]
    best_interest = first(meaningful_interests)
    best_age_gender = first(meaningful_age_gender)

    adset_lines = [
        f"{index}. {item['label']}: {audience_metric_sentence(item)}. {audience_diagnosis(item)}"
        for index, item in enumerate(top_adsets, start=1)
    ]
    interest_lines = [
        f"{index}. {item['label']}: {audience_metric_sentence(item)}."
        for index, item in enumerate(meaningful_interests[:5], start=1)
    ]

    return (
        "Audience specialist ranking from the saved Meta knowledge base:\n"
        + ("Top ad sets:\n" + "\n".join(adset_lines) if adset_lines else "Top ad sets: not enough meaningful ad set data.")
        + "\n\nTop interest clusters:\n"
        + ("\n".join(interest_lines) if interest_lines else "Not enough meaningful interest data.")
        + (
            f"\n\nBest age/gender hypothesis: {best_age_gender['label']} with {as_float(best_age_gender.get('leads')):,.0f} leads, "
            f"CPL ${as_float(best_age_gender.get('cpl')):.2f}, lead rate {as_float(best_age_gender.get('leadRateFromClick')):.1f}%."
            if best_age_gender
            else "\n\nBest age/gender hypothesis: not enough meaningful age/gender data yet."
        )
        + (
            f"\nBest interest hypothesis: {best_interest['label']} with {as_float(best_interest.get('leads')):,.0f} leads, "
            f"CPL ${as_float(best_interest.get('cpl')):.2f}, lead rate {as_float(best_interest.get('leadRateFromClick')):.1f}%."
            if best_interest
            else "\nBest interest hypothesis: not enough meaningful interest data yet."
        )
        + "\nRecommendation: use the best ad set or interest as a test hypothesis, not a final buyer audience. "
        "Because attributed purchases are missing or sparse, decide scaling with Telegram START quality, CRM stages, and sales capacity. "
        "For higher purchasing power, prefer full-time job, business, marketing/SMM, small-business, and AI-workflow angles over broad curiosity-only audiences."
    )


def rank_raw_insight_rows(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = raw_label_for(row, keys)
        current = grouped.setdefault(
            label,
            {"id": str(row.get(keys[0]) or ""), "label": label, "spend": 0.0, "clicks": 0.0, "leads": 0.0, "purchases": 0.0},
        )
        current["spend"] += as_float(row.get("spend"))
        current["clicks"] += as_float(row.get("clicks"))
        current["leads"] += action_count(row, "lead") + action_count(row, "registration")
        current["purchases"] += action_count(row, "purchase")
    return sorted((with_audience_rates(item) for item in grouped.values()), key=audience_sort_key)


def raw_label_for(row: dict[str, Any], keys: list[str]) -> str:
    if keys == ["adset_id", "adset_name"]:
        return str(row.get("adset_name") or row.get("adset_id") or "Unknown")
    parts = [str(row.get(key) or "") for key in keys if row.get(key)]
    return " / ".join(parts) if parts else "Unknown"


def with_audience_rates(item: dict[str, Any]) -> dict[str, Any]:
    clicks = as_float(item.get("clicks"))
    leads = as_float(item.get("leads"))
    spend = as_float(item.get("spend"))
    return {
        **item,
        "cpc": spend / clicks if clicks else 0,
        "cpl": spend / leads if leads else 0,
        "leadRateFromClick": (leads / clicks * 100) if clicks else 0,
    }


def audience_sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
    cpl = as_float(item.get("cpl"))
    leads = as_float(item.get("leads"))
    spend = as_float(item.get("spend"))
    return (cpl if cpl else 999999, -leads, -spend)


def has_meaningful_audience_evidence(item: dict[str, Any], min_spend: float) -> bool:
    return as_float(item.get("spend")) >= min_spend or as_float(item.get("clicks")) >= 500 or as_float(item.get("leads")) >= 100


def audience_metric_sentence(item: dict[str, Any]) -> str:
    return (
        f"${as_float(item.get('spend')):,.2f} spend, {as_float(item.get('clicks')):,.0f} clicks, "
        f"{as_float(item.get('leads')):,.0f} leads, {as_float(item.get('purchases')):,.0f} purchases, "
        f"CPC ${as_float(item.get('cpc')):.4f}, CPL ${as_float(item.get('cpl')):.2f}, "
        f"lead rate {as_float(item.get('leadRateFromClick')):.1f}%"
    )


def audience_diagnosis(item: dict[str, Any]) -> str:
    leads = as_float(item.get("leads"))
    purchases = as_float(item.get("purchases"))
    label = str(item.get("label", "")).lower()
    if purchases > 0:
        return "Scale candidate: has downstream purchase proof."
    if leads >= 100 and purchases == 0:
        if any(word in label for word in ["business", "marketing", "smm", "ai", "work", "job"]):
            return "Qualified-lead candidate: validate Telegram/CRM quality before scaling."
        return "Lead-volume candidate: check purchasing power before scaling."
    return "Learning candidate: keep broad until more downstream quality data arrives."


def answer_placements_from_knowledge_base(knowledge: dict[str, Any]) -> str:
    analysis = knowledge.get("analysis", {})
    min_spend = max(5, analysis.get("summary", {}).get("spend", 0) * 0.02)
    placements = [
        item
        for item in analysis.get("placements", [])
        if as_float(item.get("spend")) >= min_spend or as_float(item.get("clicks")) >= 500 or as_float(item.get("leads")) >= 100
    ]
    if not placements:
        return (
            "Placement specialist ranking: not enough placement breakdown data yet. "
            "Refresh Meta insights with publisher_platform and platform_position breakdowns before deciding where to scale or cut."
        )

    ranked = sorted(placements, key=placement_sort_key)
    weak = max(ranked, key=placement_waste_key)
    instagram = [item for item in ranked if "instagram" in str(item.get("label", "")).lower()]
    facebook = [item for item in ranked if "facebook" in str(item.get("label", "")).lower()]
    top_lines = [
        f"{index}. {item['label']}: {placement_metric_sentence(item)}. {placement_diagnosis(item)}"
        for index, item in enumerate(ranked[:6], start=1)
    ]

    return (
        "Placement specialist ranking from the saved Meta knowledge base:\n"
        + "\n".join(top_lines)
        + f"\n\nScale hypothesis: {ranked[0]['label']} has the strongest placement signal by CPL, lead rate, and volume."
        + f"\nPlacement to avoid or isolate: {weak['label']} because it shows weaker cost/quality economics relative to the account."
        + (
            f"\nInstagram vs Facebook read: Instagram best candidate is {instagram[0]['label'] if instagram else 'not enough Instagram data'}; "
            f"Facebook best candidate is {facebook[0]['label'] if facebook else 'not enough Facebook data'}."
        )
        + "\nRecommendation: separate Instagram placements from Facebook tests, especially in Uzbekistan, so cheap Facebook traffic does not hide weak downstream quality. "
        "Scale only after Telegram START and CRM quality confirm that registrations are turning into reachable, qualified leads."
    )


def placement_sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
    cpl = as_float(item.get("cpl"))
    lead_rate = as_float(item.get("leadRateFromClick"))
    leads = as_float(item.get("leads"))
    return (cpl if cpl else 999999, -lead_rate, -leads)


def placement_waste_key(item: dict[str, Any]) -> tuple[float, float, float]:
    cpl = as_float(item.get("cpl"))
    spend = as_float(item.get("spend"))
    leads = as_float(item.get("leads"))
    return (cpl if cpl else 999999, spend, -leads)


def placement_metric_sentence(item: dict[str, Any]) -> str:
    return (
        f"${as_float(item.get('spend')):,.2f} spend, {as_float(item.get('clicks')):,.0f} clicks, "
        f"{as_float(item.get('leads')):,.0f} leads, {as_float(item.get('purchases')):,.0f} purchases, "
        f"CPC ${as_float(item.get('cpc')):.4f}, CPL ${as_float(item.get('cpl')):.2f}, "
        f"lead rate {as_float(item.get('leadRateFromClick')):.1f}%"
    )


def placement_diagnosis(item: dict[str, Any]) -> str:
    label = str(item.get("label", "")).lower()
    purchases = as_float(item.get("purchases"))
    leads = as_float(item.get("leads"))
    if purchases > 0:
        return "Scale candidate: has downstream purchase proof."
    if "instagram" in label and leads >= 100:
        return "Priority test: matches the known Uzbekistan Instagram behavior, but still needs Telegram/CRM validation."
    if "facebook" in label:
        return "Isolation candidate: keep separate or retarget-only until buyer quality is proven."
    return "Controlled test candidate: judge by Telegram START and CRM quality, not clicks alone."


def answer_funnel_from_knowledge_base(knowledge: dict[str, Any]) -> str:
    tracking = tracking_calculations_from_knowledge(knowledge)
    clicks = as_float(tracking.get("clicks"))
    visits = as_float(tracking.get("estimatedLandingPageVisits"))
    leads = as_float(tracking.get("leads"))
    purchases = as_float(tracking.get("purchases"))
    visit_rate = as_float(tracking.get("visitRatePercent"))
    landing_lead_rate = as_float(tracking.get("landingPageLeadRatePercent"))
    purchase_rate = as_float(tracking.get("purchaseRateFromLandingVisitPercent"))
    leak = funnel_leak_label(visit_rate, landing_lead_rate, purchases, visits)

    return (
        "Funnel specialist diagnosis from the saved Meta knowledge base:\n"
        f"1. Ad click to landing page: {clicks:,.0f} clicks -> {visits:,.0f} landing visits, landing visit rate {visit_rate:.1f}%.\n"
        f"2. Landing page to registration: {visits:,.0f} landing visits -> {leads:,.0f} leads, landing lead rate {landing_lead_rate:.1f}%.\n"
        f"3. Landing page to purchase: {purchases:,.0f} purchases, purchase rate from landing visit {purchase_rate:.1f}%.\n"
        f"Biggest current leak: {leak}. "
        "Telegram START rate is not fully attributable until each bot deep link sends visitor_id and telegram_user_id back to the tracker. "
        "CRM purchase data is also required before the agent can confidently choose scale winners. "
        "Recommendation: watch landing visit rate, landing lead rate, Telegram START rate, and CRM qualified/paid stages together before increasing budgets."
    )


def funnel_leak_label(visit_rate: float, landing_lead_rate: float, purchases: float, visits: float) -> str:
    if visit_rate < 70:
        return "click-to-landing-page handoff, likely page speed, redirect, or intent mismatch"
    if landing_lead_rate < 35:
        return "landing-page-to-lead conversion, likely promise/CTA/VSL-bot expectation mismatch"
    if visits > 0 and purchases == 0:
        return "post-lead quality, because registrations exist but CRM purchases are not attributed"
    return "downstream Telegram/CRM quality; keep monitoring because top-of-funnel rates look usable"


def answer_creatives_from_knowledge_base(knowledge: dict[str, Any]) -> str:
    analysis = knowledge.get("analysis", {})
    top_ads = analysis.get("topAds", []) or []
    if not top_ads:
        return "The saved knowledge base does not have creative-level Meta analysis yet. Refresh ads and insights first."

    raw_ads = knowledge.get("raw", {}).get("ads", []) or []
    ad_lookup = {str(ad.get("id")): ad for ad in raw_ads}
    meaningful = [item for item in top_ads if has_meaningful_creative_evidence(item)]
    ranked = meaningful or top_ads[:5]
    top_lines = []
    for index, item in enumerate(ranked[:5], start=1):
        top_lines.append(f"{index}. {creative_label(item)}: {creative_metric_sentence(item)}; {creative_media_sentence(item, ad_lookup)}")

    scale = first(ranked)
    traffic_magnet = max(ranked, key=lambda item: (as_float(item.get("leads")), as_float(item.get("clicks")))) if ranked else None
    weak_buyer = first([item for item in ranked if as_float(item.get("leads")) > 0 and as_float(item.get("purchases")) == 0])

    return (
        "Creative specialist ranking from the saved Meta knowledge base:\n"
        + "\n".join(top_lines)
        + (
            f"\n\nScale candidate: {creative_label(scale)} has the strongest usable creative signal in the saved data. "
            "Replicate the hook only if Telegram START and CRM quality are acceptable."
            if scale
            else "\n\nScale candidate: not enough meaningful creative data yet."
        )
        + (
            f"\nTraffic magnet to audit: {creative_label(traffic_magnet)} generated "
            f"{as_float(traffic_magnet.get('leads')):,.0f} leads from {as_float(traffic_magnet.get('clicks')):,.0f} clicks. "
            "This can be useful for attention, but it is not a buyer-quality winner until downstream quality is proven."
            if traffic_magnet
            else ""
        )
        + (
            f"\nAvoid scaling blindly: {creative_label(weak_buyer)} has registrations but no attributed purchases. "
            "Use it with higher purchasing-power audiences or rework the first seconds to qualify course value."
            if weak_buyer
            else "\nAvoid scaling blindly: no clear zero-purchase traffic magnet was found in the meaningful creative slice."
        )
    )


def has_meaningful_creative_evidence(item: dict[str, Any]) -> bool:
    return as_float(item.get("spend")) >= 5 or as_float(item.get("clicks")) >= 50 or as_float(item.get("leads")) >= 20


def creative_label(item: dict[str, Any] | None) -> str:
    if not item:
        return "not enough data"
    keys = item.get("keys", {}) or {}
    return str(keys.get("ad_name") or item.get("label") or keys.get("ad_id") or "Unknown creative")


def creative_metric_sentence(item: dict[str, Any]) -> str:
    return (
        f"${as_float(item.get('spend')):,.2f} spend, {as_float(item.get('clicks')):,.0f} clicks, "
        f"{as_float(item.get('leads')):,.0f} leads, {as_float(item.get('purchases')):,.0f} purchases, "
        f"CPC ${as_float(item.get('cpc')):.4f}, CPL ${as_float(item.get('cpl')):.2f}, "
        f"quality {as_float(item.get('qualityScore')):.1f}"
    )


def creative_media_sentence(item: dict[str, Any], ad_lookup: dict[str, dict[str, Any]]) -> str:
    keys = item.get("keys", {}) or {}
    ad_id = str(keys.get("ad_id") or "")
    ad = ad_lookup.get(ad_id) or {}
    raw_creative = ad.get("creative", {}) or {}
    analysis_creative = item.get("creative", {}) or {}
    has_thumbnail = bool(raw_creative.get("thumbnail_url") or analysis_creative.get("thumbnailUrl"))
    has_video = bool(raw_creative.get("video_id") or analysis_creative.get("videoId"))
    if has_thumbnail and has_video:
        return "thumbnail and video ID available"
    if has_thumbnail:
        return "thumbnail available"
    if has_video:
        return "video ID available"
    return "media metadata missing"


def answer_monitoring(data: dict[str, Any]) -> str:
    high_priority = [item for item in data["approvalActions"] if item.get("priority") == "high"]
    first_alert = data.get("alerts", [{}])[0]
    action_text = high_priority[0]["title"] if high_priority else first_alert.get("title", "Run the scheduled monitoring check")
    return (
        f"The Monitoring Agent should monitor cost and quality every four hours, then turn alerts into approval-safe recommendations. "
        f"Current highest-priority item: {action_text}. It should not execute pauses, budget changes, or creative rotations without approval."
    )

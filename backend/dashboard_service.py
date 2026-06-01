"""Dashboard data mapping and chat-answer helpers.

Transforms the saved Meta knowledge base into the dashboard payload and
produces the natural-language chat answers. Extracted from app.py so the web
entrypoint stays focused on routing; app.py re-imports the names it serves.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from .analysis_engine import action_count, as_float, extract_interests, valid_rows
from .campaign_watch import build_campaign_watch
from .meta_client import get_meta_config
from .monitoring_runner import list_monitoring_alerts
from .demo_dashboard import (
    ad_sets,
    ads,
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

def derive_kpis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spend = sum(row["spendUsd"] for row in rows)
    subs = sum(row["telegramSubscribers"] for row in rows)
    buyers = sum(row["purchases"] for row in rows)
    tracking = round(sum(item["matchRate"] for item in tracking_health) / len(tracking_health))
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
        "purchaseRevenueUsd": 0,
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
    return [
        {"label": "Meta Spend", "value": money(spend), "change": f"{summary.get('clicks', 0):,.0f} clicks", "helper": "Real synced Meta data", "tone": "neutral", "icon": "dollar"},
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

    if any(word in lower_question for word in ["age", "gender", "male", "female", "audience", "target"]):
        best = first_eligible_answer(analysis.get("audience", {}).get("ageGender", []), min_spend)
        interests = first_eligible_answer(analysis.get("audience", {}).get("interests", []), min_spend)
        if not best:
            return (
                "The saved Meta age/gender slice does not have enough spend per segment to recommend a reliable age/gender target yet. "
                f"The strongest interest cluster with meaningful spend is {interests['label'] if interests else 'not enough interest data'}. "
                "For now, keep age/gender broader and let creative plus conversion quality guide narrowing."
            )
        return (
            f"From the saved Meta analysis, the best-ranked age/gender segment is {best['label']}. "
            f"{best.get('spend', 0):,.2f} USD spend, {best.get('leads', 0):,.0f} leads, "
            f"{best.get('purchases', 0):,.0f} purchases, quality score {best.get('qualityScore', 0)}. "
            f"For interests, the strongest cluster is {interests['label'] if interests else 'not enough interest data'}. "
            "Use this as a test hypothesis and keep purchase/lead quality as the decision metric."
        )

    if any(word in lower_question for word in ["placement", "facebook", "instagram", "reels", "feed"]):
        eligible = [item for item in analysis.get("placements", []) if item.get("spend", 0) >= min_spend]
        placement = first(eligible)
        weak = last(eligible)
        return (
            f"Best-ranked placement with meaningful spend is {placement['label'] if placement else 'not enough placement data'}. "
            f"Weakest among meaningful-spend placements is {weak['label'] if weak else 'not enough placement data'}. "
            "I would separate placement tests rather than mixing everything blindly: scale high-quality placements and keep weak placements for retargeting only."
        )

    if any(word in lower_question for word in ["creative", "ad", "video", "worked", "didn't", "did not"]):
        top_ad = first(analysis.get("topAds", []))
        return (
            f"Top ad from the saved Meta analysis is {top_ad['label'] if top_ad else 'not enough data'}. "
            f"It produced {top_ad.get('leads', 0) if top_ad else 0:,.0f} leads and "
            f"{top_ad.get('purchases', 0) if top_ad else 0:,.0f} purchases. "
            "For creative decisions, compare high attention against downstream quality; cheap clicks alone are not enough."
        )

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
        f"That is the first place I would diagnose before scaling spend. {warning_text}"
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

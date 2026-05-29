from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .analysis_engine import action_count, as_float, build_meta_analysis, extract_interests, valid_rows
from .agent_orchestrator import agent_registry, orchestrate_agent_chat
from .approval_store import approve_request, create_approval_request, list_approval_requests, update_approval_request
from .chatplace_events import normalize_chatplace_event
from .funnel_events import build_funnel_summary, save_funnel_event
from .knowledge_base import load_knowledge_base, save_knowledge_base
from .llm_reasoner import generate_chat_answer, generate_llm_summary
from .meta_execution import build_campaign_creation_approval, execute_campaign_creation_approval
from .meta_client import (
    MetaApiError,
    get_ad_account_summary,
    get_ad_sets,
    get_ads,
    create_ad_set as meta_create_ad_set,
    create_campaign as meta_create_campaign,
    get_campaigns,
    get_insights,
    get_meta_config,
    get_token_permissions,
    get_video_source,
    mask_token,
)
from .playbook_store import load_playbooks, save_playbook
from .settings_audit import build_settings_audit
from .snapshot_store import build_snapshot_payload, list_snapshots, save_snapshot
from .strategy_generator import generate_launch_strategy

SYNC_END_DATE = date.today()

app = FastAPI(title="Meta Ad Agent API")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FUNNEL_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    suggestedQuestions: list[str]
    activeAgent: str | None = None
    routeReason: str | None = None
    generatedPlaybook: dict[str, Any] | None = None
    generatedStrategy: dict[str, Any] | None = None


class MetaSyncRequest(BaseModel):
    days: int = 90


class CampaignPlaybookRequest(BaseModel):
    playbook: dict[str, Any]


class StrategyRequest(BaseModel):
    playbook: dict[str, Any] | None = None


class CampaignExecutionPlanRequest(BaseModel):
    playbook: dict[str, Any] | None = None
    reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approvedBy: str = "akmal"


class ApprovalExecutionRequest(BaseModel):
    dryRun: bool = True
    confirmLive: bool = False


class FunnelEventRequest(BaseModel):
    event: dict[str, Any]


campaigns = [
    {
        "id": "cmp_ai_course_may_2026",
        "platform": "meta",
        "name": "AI Course Webinar - May 2026",
        "objective": "sales",
        "status": "active",
        "dailyBudgetUsd": 220,
        "startedAt": "2026-05-01",
    }
]

ad_sets = [
    {
        "id": "as_women_25_34",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 25-34 - AI income interest",
        "status": "active",
        "ageMin": 25,
        "ageMax": 34,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Artificial intelligence", "Online education", "Freelancing"],
        "placements": ["instagram_reels", "instagram_stories"],
        "optimizationGoal": "conversion",
    },
    {
        "id": "as_women_35_44",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 35-44 - high intent",
        "status": "active",
        "ageMin": 35,
        "ageMax": 44,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Business education", "Digital marketing", "Online courses"],
        "placements": ["instagram_reels", "instagram_feed", "facebook_reels"],
        "optimizationGoal": "purchase",
    },
    {
        "id": "as_young_broad",
        "campaignId": "cmp_ai_course_may_2026",
        "name": "Women 18-24 - broad creative test",
        "status": "active",
        "ageMin": 18,
        "ageMax": 24,
        "genders": ["female"],
        "locations": ["Uzbekistan"],
        "interests": ["Artificial intelligence", "ChatGPT", "Content creation"],
        "placements": ["instagram_reels", "facebook_feed", "audience_network"],
        "optimizationGoal": "lead",
    },
]

ads = [
    {"id": "ad_housewife_cartoon", "adSetId": "as_young_broad", "creativeId": "cr_housewife_cartoon", "name": "Housewife AI Cartoon", "status": "active"},
    {"id": "ad_income_case_study", "adSetId": "as_women_35_44", "creativeId": "cr_income_case_study", "name": "AI Income Case Study", "status": "active"},
    {"id": "ad_student_before_after", "adSetId": "as_women_25_34", "creativeId": "cr_student_before_after", "name": "Student Before/After", "status": "active"},
    {"id": "ad_ai_tool_montage", "adSetId": "as_women_25_34", "creativeId": "cr_ai_tool_montage", "name": "AI Tool Montage", "status": "active"},
]

creatives = [
    {"id": "cr_housewife_cartoon", "adId": "ad_housewife_cartoon", "name": "Housewife AI Cartoon", "format": "video", "theme": "Humor / relatable", "hookType": "Comedic identity hook", "primaryPersona": "Non-working female housewife", "cta": "Join free AI webinar"},
    {"id": "cr_income_case_study", "adId": "ad_income_case_study", "name": "AI Income Case Study", "format": "video", "theme": "Proof / webinar", "hookType": "Outcome proof", "primaryPersona": "Adult learner with income intent", "cta": "Reserve webinar seat"},
    {"id": "cr_student_before_after", "adId": "ad_student_before_after", "name": "Student Before/After", "format": "video", "theme": "Transformation", "hookType": "Before and after", "primaryPersona": "Beginner AI student", "cta": "Start learning AI"},
    {"id": "cr_ai_tool_montage", "adId": "ad_ai_tool_montage", "name": "AI Tool Montage", "format": "video", "theme": "Feature demo", "hookType": "Fast tool reveal", "primaryPersona": "AI-curious creator", "cta": "See the tools in class"},
]

creative_analyses = [
    {
        "creativeId": "cr_housewife_cartoon",
        "viralScore": 94,
        "buyerIntentScore": 31,
        "courseFitScore": 42,
        "purchasingPowerScore": 28,
        "funnelQualityScore": 36,
        "hookSummary": "Relatable humor gets attention quickly.",
        "conversionRisk": "Audience may consume it as entertainment instead of a paid learning path.",
        "recommendedAction": "Retool message",
        "sceneNotes": [
            "First seconds use exaggerated facial expression and household context.",
            "Middle section creates comedy but does not establish course value.",
            "CTA arrives after the joke, so buyer intent is weak.",
        ],
        "whyItWorked": "The setup feels familiar and easy to share, so it earns cheap attention.",
        "whyItDidNotConvert": "The viewer is entertained before they are qualified for a paid AI course.",
    },
    {
        "creativeId": "cr_income_case_study",
        "viralScore": 64,
        "buyerIntentScore": 88,
        "courseFitScore": 92,
        "purchasingPowerScore": 84,
        "funnelQualityScore": 89,
        "hookSummary": "Proof-led intro qualifies viewers early.",
        "conversionRisk": "May need more emotional contrast to scale.",
        "recommendedAction": "Scale carefully",
        "sceneNotes": [
            "Opening promise is specific and tied to income outcome.",
            "Proof segment gives the audience a reason to trust the webinar.",
            "CTA aligns with the course offer and attracts fewer low-intent clicks.",
        ],
        "whyItWorked": "The creative filters for people who want practical AI income skills.",
        "whyItDidNotConvert": "It may feel less entertaining at cold scale, so hook variety is needed.",
    },
    {
        "creativeId": "cr_student_before_after",
        "viralScore": 71,
        "buyerIntentScore": 79,
        "courseFitScore": 86,
        "purchasingPowerScore": 76,
        "funnelQualityScore": 81,
        "hookSummary": "Transformation is clear and course-aligned.",
        "conversionRisk": "Needs stronger urgency for webinar attendance.",
        "recommendedAction": "Duplicate test",
        "sceneNotes": [
            "Before/after contrast is easy to understand.",
            "Learning path is visible, which improves course fit.",
            "The CTA could be moved earlier for better webinar show-up.",
        ],
        "whyItWorked": "It shows a believable path from beginner to capable AI user.",
        "whyItDidNotConvert": "The next action is not urgent enough for some viewers.",
    },
    {
        "creativeId": "cr_ai_tool_montage",
        "viralScore": 82,
        "buyerIntentScore": 48,
        "courseFitScore": 61,
        "purchasingPowerScore": 46,
        "funnelQualityScore": 52,
        "hookSummary": "Fast visuals pull clicks from AI-curious viewers.",
        "conversionRisk": "Feature curiosity is weaker than purchase intent.",
        "recommendedAction": "Add offer clarity",
        "sceneNotes": [
            "Rapid tool switching creates attention and novelty.",
            "The course connection is implied instead of stated.",
            "A clearer transformation would help qualify paid learners.",
        ],
        "whyItWorked": "Tool reveals create curiosity and high click volume.",
        "whyItDidNotConvert": "Curiosity about tools does not automatically mean readiness to buy a course.",
    },
]

metrics = [
    {"date": "2026-05-01", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_young_broad", "adId": "ad_housewife_cartoon", "creativeId": "cr_housewife_cartoon", "placement": "instagram_reels", "spendUsd": 118, "impressions": 62000, "clicks": 2600, "landingPageViews": 2070, "leads": 420, "telegramSubscribers": 238, "webinarAttendees": 52, "purchases": 2, "purchaseRevenueUsd": 460},
    {"date": "2026-05-04", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_stories", "spendUsd": 132, "impressions": 51000, "clicks": 920, "landingPageViews": 812, "leads": 132, "telegramSubscribers": 88, "webinarAttendees": 31, "purchases": 4, "purchaseRevenueUsd": 920},
    {"date": "2026-05-07", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_25_34", "adId": "ad_student_before_after", "creativeId": "cr_student_before_after", "placement": "instagram_reels", "spendUsd": 156, "impressions": 74000, "clicks": 1840, "landingPageViews": 1450, "leads": 284, "telegramSubscribers": 164, "webinarAttendees": 44, "purchases": 5, "purchaseRevenueUsd": 1150},
    {"date": "2026-05-10", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_25_34", "adId": "ad_ai_tool_montage", "creativeId": "cr_ai_tool_montage", "placement": "facebook_feed", "spendUsd": 171, "impressions": 83000, "clicks": 3120, "landingPageViews": 2290, "leads": 438, "telegramSubscribers": 214, "webinarAttendees": 39, "purchases": 3, "purchaseRevenueUsd": 690},
    {"date": "2026-05-13", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_reels", "spendUsd": 188, "impressions": 68500, "clicks": 1260, "landingPageViews": 1010, "leads": 194, "telegramSubscribers": 126, "webinarAttendees": 43, "purchases": 6, "purchaseRevenueUsd": 1380},
    {"date": "2026-05-16", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "facebook_reels", "spendUsd": 205, "impressions": 72000, "clicks": 1320, "landingPageViews": 1090, "leads": 212, "telegramSubscribers": 141, "webinarAttendees": 50, "purchases": 7, "purchaseRevenueUsd": 1610},
    {"date": "2026-05-19", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_young_broad", "adId": "ad_housewife_cartoon", "creativeId": "cr_housewife_cartoon", "placement": "audience_network", "spendUsd": 218, "impressions": 104000, "clicks": 3640, "landingPageViews": 2510, "leads": 510, "telegramSubscribers": 244, "webinarAttendees": 36, "purchases": 4, "purchaseRevenueUsd": 920},
    {"date": "2026-05-21", "campaignId": "cmp_ai_course_may_2026", "adSetId": "as_women_35_44", "adId": "ad_income_case_study", "creativeId": "cr_income_case_study", "placement": "instagram_reels", "spendUsd": 226, "impressions": 67500, "clicks": 1280, "landingPageViews": 1110, "leads": 228, "telegramSubscribers": 151, "webinarAttendees": 61, "purchases": 8, "purchaseRevenueUsd": 1840},
]

audience = [
    {"segment": "25-34 Women", "spend": 1180, "subs": 352, "buyers": 21},
    {"segment": "35-44 Women", "spend": 920, "subs": 246, "buyers": 28},
    {"segment": "18-24 Women", "spend": 760, "subs": 390, "buyers": 5},
    {"segment": "AI Interest Broad", "spend": 1240, "subs": 281, "buyers": 13},
    {"segment": "Retarget 30D", "spend": 720, "subs": 113, "buyers": 7},
]

insights = [
    {"icon": "trendingDown", "title": "Viral traffic is not buyer traffic", "body": "The cartoon housewife creative is winning clicks but losing after Telegram. Keep the hook, but qualify viewers with course value before second 6.", "tone": "warning"},
    {"icon": "target", "title": "35-44 women show stronger purchasing power", "body": "This group has fewer clicks than 18-24, but 4.2x stronger buyer rate. Shift the next test toward intent and proof-based creative.", "tone": "good"},
    {"icon": "alert", "title": "Facebook Feed is leaking budget", "body": "FB Feed uses 18% of spend but produces 5% of buyers. Keep it for retargeting only until cold performance improves.", "tone": "danger"},
]

experiments = [
    {"title": "Retool viral cartoon into buyer-intent version", "metric": "Qualified Telegram subscriber below $3.50", "budget": "$45/day for 3 days"},
    {"title": "Scale proof-led case study creative", "metric": "Cost per buyer below $58", "budget": "$70/day with 20% daily cap"},
    {"title": "Placement split: IG Reels vs IG Stories", "metric": "Webinar attendance rate above 28%", "budget": "$30/day per placement"},
]

tracking_health = [
    {"name": "Meta Pixel", "status": "healthy", "matchRate": 94, "lastEventAt": "2026-05-21 18:42", "note": "Browser events are arriving from the landing page."},
    {"name": "Conversions API", "status": "healthy", "matchRate": 91, "lastEventAt": "2026-05-21 18:40", "note": "Server events are matching pixel events with stable deduplication."},
    {"name": "Landing Page Lead Form", "status": "warning", "matchRate": 78, "lastEventAt": "2026-05-21 18:15", "note": "Visit-to-lead rate dropped on mobile traffic."},
    {"name": "Telegram Bot Start", "status": "healthy", "matchRate": 88, "lastEventAt": "2026-05-21 18:33", "note": "Subscriber attribution is preserving campaign and creative IDs."},
    {"name": "Webinar Attendance", "status": "warning", "matchRate": 72, "lastEventAt": "2026-05-21 17:50", "note": "Attendance import is delayed and should be monitored."},
    {"name": "Purchase Events", "status": "healthy", "matchRate": 86, "lastEventAt": "2026-05-21 18:11", "note": "Buyer events include value and source attribution."},
]

approval_actions = [
    {"id": "act_pause_fb_feed_cold", "title": "Move Facebook Feed out of cold campaigns", "impact": "Reduce spend leakage from low-buyer traffic.", "risk": "medium", "owner": "human", "status": "needs_review"},
    {"id": "act_scale_case_study", "title": "Increase case study budget by 20%", "impact": "Give strongest buyer-intent creative more delivery.", "risk": "low", "owner": "agent", "status": "ready"},
    {"id": "act_retool_cartoon", "title": "Create buyer-intent version of cartoon creative", "impact": "Keep viral hook while qualifying course buyers earlier.", "risk": "low", "owner": "human", "status": "ready"},
    {"id": "act_check_mobile_landing", "title": "Audit mobile landing page lead drop", "impact": "Recover lost leads before scaling budget.", "risk": "high", "owner": "human", "status": "blocked"},
]

glossary = [
    {"metric": "Qualified Telegram Subscriber", "definition": "A subscriber attributed to an ad who joins Telegram and shows a quality signal such as staying, clicking, or webinar intent.", "watchFor": "If this rises while clicks stay cheap, the creative may be attracting the wrong audience."},
    {"metric": "Landing Visit Rate", "definition": "Landing page views divided by ad clicks.", "watchFor": "A drop often means slow page load, broken tracking, or click quality issues."},
    {"metric": "Buyer Intent Score", "definition": "Creative analysis score estimating whether the message attracts people likely to pay for AI courses.", "watchFor": "High viral score with low buyer intent is a warning sign."},
    {"metric": "Funnel Quality Score", "definition": "Combined score from lead rate, Telegram join rate, webinar attendance, and purchases.", "watchFor": "Use this to decide what to scale, not CTR alone."},
    {"metric": "Placement Waste", "definition": "A placement that spends materially more than its buyer contribution.", "watchFor": "Cold campaigns should not keep placements that spend but do not produce buyers."},
]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta/status")
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


@app.get("/api/meta/campaigns")
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


@app.get("/api/meta/permissions")
async def meta_permissions() -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"configured": False, "permissions": [], "error": "Add META_ACCESS_TOKEN and META_AD_ACCOUNT_ID to .env."}
    try:
        return {"configured": True, "permissions": await get_token_permissions(config), "error": None}
    except MetaApiError as error:
        return {"configured": True, "permissions": [], "error": str(error)}


@app.get("/api/meta/video/{video_id}")
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


@app.post("/api/meta/sync")
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


@app.get("/api/meta/snapshots")
def meta_snapshots() -> dict[str, Any]:
    return {"snapshots": list_snapshots()}


@app.get("/api/meta/settings-audit")
def meta_settings_audit() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if not knowledge:
        return {"available": False, "error": "No Meta sync has been saved yet.", "audit": None}
    return {"available": True, "audit": build_settings_audit(knowledge.get("raw", {}))}


@app.get("/api/playbooks")
def campaign_playbooks() -> dict[str, Any]:
    return {"playbooks": load_playbooks()}


@app.post("/api/playbooks")
def upsert_campaign_playbook(request: CampaignPlaybookRequest) -> dict[str, Any]:
    return {"playbook": save_playbook(request.playbook)}


@app.post("/api/strategy/generate")
def generate_strategy(request: StrategyRequest) -> dict[str, Any]:
    playbook = request.playbook or load_playbooks()[0]
    knowledge = load_knowledge_base()
    return {
        "ok": True,
        "strategy": generate_launch_strategy(playbook, knowledge),
        "knowledgeAvailable": bool(knowledge),
    }


@app.get("/api/approvals")
def approvals() -> dict[str, Any]:
    return {"approvals": list_approval_requests()}


@app.post("/api/execution/prepare-campaign")
def prepare_campaign_execution(request: CampaignExecutionPlanRequest) -> dict[str, Any]:
    playbook = request.playbook or first_playbook_with_segments(load_playbooks())
    if not playbook:
        raise HTTPException(status_code=400, detail="Save a playbook with at least one segment before preparing execution.")

    account_id = get_meta_config().ad_account_id or "unconfigured_ad_account"
    approval = build_campaign_creation_approval(
        playbook,
        account_id=account_id,
        reason=request.reason or "Prepare a paused Meta campaign structure for review.",
    )
    return {"ok": True, "approval": create_approval_request(approval)}


@app.post("/api/approvals/{approval_id}/approve")
def approve_approval_request(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
    try:
        return {"ok": True, "approval": approve_request(approval_id, approved_by=request.approvedBy)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/approvals/{approval_id}/execute")
async def execute_approval_request(approval_id: str, request: ApprovalExecutionRequest) -> dict[str, Any]:
    approval = next((item for item in list_approval_requests() if item.get("id") == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")

    config = get_meta_config()
    result = await execute_campaign_creation_approval(
        approval,
        dry_run=request.dryRun,
        confirm_live=request.confirmLive,
        live_writes_enabled=os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true",
        create_campaign=lambda payload: meta_create_campaign(config, payload),
        create_ad_set=lambda payload: meta_create_ad_set(config, payload),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Execution failed."))

    status = "dry_run_completed" if request.dryRun else "executed"
    updated = update_approval_request(
        approval_id,
        {
            "status": status,
            "lastExecutionResult": result,
        },
    )
    return {"ok": True, "approval": updated, "result": result}


@app.get("/api/agents")
def agents() -> dict[str, Any]:
    live_writes_enabled = os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true"
    return {
        "agents": list(agent_registry().values()),
        "executionEnabled": live_writes_enabled,
        "approvalRequiredForLiveChanges": True,
        "liveWriteScope": "paused_campaign_and_adset_creation_only" if live_writes_enabled else "disabled",
    }


async def safe_insights(config: Any, breakdowns: list[str]) -> list[dict[str, Any]]:
    try:
        return await get_insights(config, breakdowns=breakdowns)
    except MetaApiError as error:
        return [{"sync_error": str(error), "breakdowns": ",".join(breakdowns)}]


async def safe_chunked_insights(
    config: Any,
    name: str,
    breakdowns: list[str] | None,
    *,
    days: int = 90,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for current, chunk_end in build_sync_windows(days=days, end_date=SYNC_END_DATE):
        try:
            rows.extend(await get_insights(config, breakdowns=breakdowns, since=current.isoformat(), until=chunk_end.isoformat()))
        except MetaApiError as error:
            errors.append({
                "sync_error": str(error),
                "source": name,
                "since": current.isoformat(),
                "until": chunk_end.isoformat(),
            })

    return rows or errors


def normalize_sync_days(days: int) -> int:
    if days <= 0:
        return 90
    return min(days, 186)


def build_sync_windows(*, days: int, end_date: date, chunk_days: int = 7) -> list[tuple[date, date]]:
    days = normalize_sync_days(days)
    start = end_date - timedelta(days=days - 1)
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        windows.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return windows


async def safe_list(name: str, awaitable: Any) -> list[dict[str, Any]]:
    try:
        return await awaitable
    except MetaApiError as error:
        return [{"sync_error": str(error), "source": name}]


@app.get("/api/knowledge-base")
def knowledge_base() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if not knowledge:
        return {"available": False, "error": "No Meta sync has been saved yet."}
    return {"available": True, "knowledge": knowledge}


@app.post("/api/funnel/events")
def ingest_funnel_event(request: FunnelEventRequest) -> dict[str, Any]:
    event = save_funnel_event(request.event)
    return {"ok": True, "event": event, "summary": build_funnel_summary()}


@app.post("/api/chatplace/events")
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


@app.get("/api/funnel/summary")
def funnel_event_summary() -> dict[str, Any]:
    return build_funnel_summary()


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if knowledge:
        return dashboard_from_knowledge_base(knowledge)

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
        "approvalActions": approval_actions,
        "glossary": glossary,
        "dataSource": {
            "kind": "mock",
            "label": "Mock dashboard model",
            "generatedAt": None,
            "syncErrors": [],
        },
    }


@app.get("/api/dashboard.js")
def dashboard_script(callback: str = "__META_AD_AGENT_DASHBOARD__") -> Response:
    safe_callback = "".join(character for character in callback if character.isalnum() or character in "._$")
    if not safe_callback:
        safe_callback = "__META_AD_AGENT_DASHBOARD__"
    return Response(
        content=f"{safe_callback}({json.dumps(dashboard(), ensure_ascii=False)});",
        media_type="application/javascript",
    )


@app.post("/api/agent/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest) -> ChatResponse:
    question = request.message.strip()
    if not question:
        return ChatResponse(
            answer="Ask me about creatives, audiences, placements, funnel leaks, experiments, or Meta connection status.",
            sources=["agent"],
            suggestedQuestions=default_questions(),
        )

    lower = question.lower()
    dashboard_data = dashboard()
    meta = await meta_status()
    knowledge = load_knowledge_base()
    orchestrated = orchestrate_agent_chat(question, knowledge=knowledge, playbooks=load_playbooks())
    if orchestrated:
        generated_playbook = orchestrated.get("generatedPlaybook")
        if generated_playbook:
            saved_playbook = save_playbook(generated_playbook)
            orchestrated["generatedPlaybook"] = saved_playbook
            if orchestrated.get("generatedStrategy"):
                orchestrated["generatedStrategy"]["playbookId"] = saved_playbook["id"]
            orchestrated["answer"] += "\n\nI saved this as a draft playbook in the dashboard. It is still not executed in Meta Ads."
        return ChatResponse(**orchestrated)

    wants_tracking_answer = any(word in lower for word in ["pixel", "tracking", "visit", "landing", "lead rate", "funnel"])
    wants_connection_status = any(word in lower for word in ["token", "meta api", "account id", "ad account", "api status"])
    if wants_connection_status and not wants_tracking_answer:
        return ChatResponse(
            answer=answer_meta_status(meta),
            sources=["/api/meta/status"],
            suggestedQuestions=[
                "Can you pull my campaigns now?",
                "What Meta data do we still need?",
                "What is the next integration step?",
            ],
        )

    if knowledge:
        try:
            llm_answer = await generate_chat_answer(question, knowledge_chat_preview(knowledge))
        except Exception:
            llm_answer = None
        if llm_answer and not llm_answer.startswith("LLM chat unavailable"):
            return ChatResponse(
                answer=llm_answer,
                sources=["storage/meta_knowledge_base.json", "openai"],
                suggestedQuestions=[
                    "Which audience should we scale?",
                    "How is lead percentage calculated?",
                    "What should we test next?",
                ],
            )
        kb_answer = answer_from_knowledge_base(lower, knowledge)
        if kb_answer:
            return ChatResponse(
                answer=kb_answer,
                sources=["storage/meta_knowledge_base.json"],
                suggestedQuestions=[
                    "Which age and gender should we target?",
                    "Should we target country or region?",
                    "Which placements should we avoid?",
                ],
            )

    if any(word in lower for word in ["connect", "token", "meta", "account", "api"]) and not wants_tracking_answer:
        return ChatResponse(
            answer=answer_meta_status(meta),
            sources=["/api/meta/status"],
            suggestedQuestions=[
                "Can you pull my campaigns now?",
                "What Meta data do we still need?",
                "What is the next integration step?",
            ],
        )

    if any(word in lower for word in ["creative", "video", "hook", "viral", "convert", "conversion"]):
        return ChatResponse(
            answer=answer_creatives(dashboard_data),
            sources=["creativeAnalyses", "metrics"],
            suggestedQuestions=[
                "Which creative should we replicate?",
                "Why did the viral creative not convert?",
                "What creative should we test next?",
            ],
        )

    if any(word in lower for word in ["audience", "age", "buyer", "purchasing", "target"]):
        return ChatResponse(
            answer=answer_audiences(dashboard_data),
            sources=["audience", "metrics"],
            suggestedQuestions=[
                "Which audience should we scale?",
                "Which audience has weak purchasing power?",
                "What targeting should we test next?",
            ],
        )

    if any(word in lower for word in ["placement", "facebook", "instagram", "reels", "feed"]):
        return ChatResponse(
            answer=answer_placements(dashboard_data),
            sources=["placements", "metrics"],
            suggestedQuestions=[
                "Should we turn off Facebook Feed?",
                "Which placement is best for buyers?",
                "How should we split placement budget?",
            ],
        )

    if any(word in lower for word in ["funnel", "telegram", "landing", "webinar", "lead", "leak"]):
        return ChatResponse(
            answer=answer_funnel(dashboard_data),
            sources=["funnel", "trackingHealth"],
            suggestedQuestions=[
                "Where is the biggest funnel leak?",
                "How can we improve Telegram join rate?",
                "Which funnel metric should we watch daily?",
            ],
        )

    if any(word in lower for word in ["experiment", "test", "budget", "scale", "pause", "recommend"]):
        return ChatResponse(
            answer=answer_experiments(dashboard_data),
            sources=["experiments", "approvalActions"],
            suggestedQuestions=[
                "What should we test first?",
                "What should we pause?",
                "What is the safest budget move?",
            ],
        )

    return ChatResponse(
        answer=answer_summary(dashboard_data, meta),
        sources=["dashboard", "/api/meta/status"],
        suggestedQuestions=default_questions(),
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
                "The saved 90-day age/gender slice does not have enough spend per segment to recommend a reliable age/gender target yet. "
                f"The strongest interest cluster with meaningful spend is {interests['label'] if interests else 'not enough interest data'}. "
                "For now, keep age/gender broader and let creative plus conversion quality guide narrowing."
            )
        return (
            f"From the saved 90-day Meta analysis, the best-ranked age/gender segment is {best['label']}. "
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
            f"Top ad from the saved 90-day analysis is {top_ad['label'] if top_ad else 'not enough data'}. "
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
    return {
        "role": "canonical_90_day_meta_ads_knowledge_base",
        "instructions": [
            "Use this as the source of truth for the user's Meta ads account.",
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

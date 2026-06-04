from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SHAHLO_PLACEMENT_PRIORITY = ["instagram_reels", "instagram_stories", "instagram_feed"]
WEAK_COLD_PLACEMENTS = {"facebook_feed", "facebook_reels", "audience_network", "messenger"}


def generate_launch_strategy(playbook: dict[str, Any], knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    analysis = (knowledge or {}).get("analysis", {})
    rules = playbook.get("rules", {})
    segments = playbook.get("segments", []) or []
    default_budget = as_float(rules.get("startingBudgetUsd"), 100)
    capacity = as_float(rules.get("salesCapacityLeadsPerDay"), 0)
    cpl = max(as_float(analysis.get("summary", {}).get("cpl"), 1), 0.01)

    strategy_segments = [
        build_segment_strategy(segment, analysis, default_budget)
        for segment in segments
    ]
    total_budget = round(sum(segment["budgetUsd"] for segment in strategy_segments), 2)
    estimated_leads = round(total_budget / cpl, 1) if total_budget else 0
    risks = build_risks(strategy_segments, analysis, estimated_leads, capacity)

    strategy = {
        "id": f"strategy_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "playbookId": playbook.get("id", "pb_default"),
        "playbookName": playbook.get("name", "Configurable launch playbook"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": build_summary(playbook, analysis, strategy_segments, total_budget),
        "execution": {
            "mode": "approval_only",
            "requiresApproval": bool(rules.get("requiresApprovalForExecution", True)),
            "approvalChannels": playbook.get("approvalChannels", ["dashboard"]),
        },
        "budget": {
            "totalDailyBudgetUsd": total_budget,
            "maxDailyBudgetUsd": as_float(rules.get("maxDailyBudgetUsd"), total_budget),
            "scalingStepPercent": as_float(rules.get("scalingStepPercent"), 20),
            "scalingFrequencyDays": as_float(rules.get("scalingFrequencyDays"), 1),
            "salesCapacityLeadsPerDay": capacity,
            "estimatedDailyLeadLoad": estimated_leads,
            "split": [
                {
                    "segmentId": segment["id"],
                    "segmentName": segment["name"],
                    "dailyBudgetUsd": segment["budgetUsd"],
                    "sharePercent": round((segment["budgetUsd"] / total_budget) * 100, 1) if total_budget else 0,
                }
                for segment in strategy_segments
            ],
        },
        "segments": strategy_segments,
        "testMatrix": build_test_matrix(strategy_segments, playbook, analysis),
        "approvalActions": build_approval_actions(strategy_segments, risks, playbook),
        "risks": risks,
        "knowledgeUsed": build_knowledge_used(analysis),
        "assumptions": [
            f"Optimize first for {playbook.get('primarySuccessMetric', 'telegram_start')} until CRM purchase data is connected.",
            "Use paid course purchase quality as the final decision signal when Bitrix24 or sales exports become available.",
            "Keep Meta changes approval-gated; the agent recommends actions before executing them.",
        ],
    }
    strategy["launchPacket"] = build_launch_packet(strategy, playbook, analysis)
    return strategy


# Frequency/CPM kill thresholds mirror the monitoring layer so the strategy's stop rule
# and the live alerts agree on what "fatigue" means.
FREQUENCY_KILL_THRESHOLD = 2.8
CPM_RISE_KILL_PERCENT = 40
# Learning needs enough daily conversions to exit promptly; a budget that funds at least
# this many target-CPA conversions per day keeps an ad set from stalling in learning.
LEARNING_DAILY_CONVERSION_TARGET = 7


def build_segment_strategy(segment: dict[str, Any], analysis: dict[str, Any], default_budget: float) -> dict[str, Any]:
    recommended_placements = choose_placements(segment, analysis)
    interests = choose_interests(segment, analysis)
    locations = segment.get("locations") or ["Uzbekistan"]
    requested_budget = as_float(segment.get("startingBudgetUsd"), default_budget)
    target_cpa = max(as_float(analysis.get("summary", {}).get("cpl"), 1), 0.01)
    min_learning_budget = round(target_cpa * LEARNING_DAILY_CONVERSION_TARGET, 2)
    budget = round(max(requested_budget, min_learning_budget), 2)
    return {
        "id": str(segment.get("id") or slug(segment.get("name", "segment"))),
        "name": segment.get("name") or "Unnamed segment",
        "budgetUsd": budget,
        "requestedBudgetUsd": requested_budget,
        "minLearningBudgetUsd": min_learning_budget,
        "budgetRationale": (
            f"Floor of ${min_learning_budget:.2f}/day funds ~{LEARNING_DAILY_CONVERSION_TARGET} conversions/day "
            f"at the ${target_cpa:.2f} target CPA so the ad set can exit the learning phase; "
            + (
                "requested budget already clears the floor."
                if requested_budget >= min_learning_budget
                else f"raised from the requested ${requested_budget:.2f}/day to protect learning."
            )
        ),
        "audienceHypothesis": segment.get("targetAudienceNotes") or infer_audience_hypothesis(segment),
        "offerAngle": segment.get("offerAngle") or "Watch the free AI income video and enter the Telegram funnel.",
        "ageRange": segment.get("ageRange") or recommended_age_range(analysis),
        "gender": segment.get("gender") or "all",
        "geoStrategy": build_geo_strategy(locations, analysis),
        "recommendedPlacements": recommended_placements,
        "interestStrategy": interests,
        "creativeAngles": build_creative_angles(segment),
        "funnelReadiness": funnel_readiness(segment),
        "budgetStrategy": choose_budget_strategy(segment),
        "scaleRule": "Increase budget by the configured step only after Telegram START and qualified-lead cost stay stable for a full review window.",
        "stopRule": (
            "Pause or reduce spend when clicks rise but Telegram START, form clicks, or sales quality falls below the segment benchmark, "
            f"or when frequency climbs above {FREQUENCY_KILL_THRESHOLD} (cold fatigue) or CPM rises more than {CPM_RISE_KILL_PERCENT}% "
            "over the comparison window — both signal audience saturation before CPL moves."
        ),
    }


def choose_budget_strategy(segment: dict[str, Any]) -> dict[str, Any]:
    """Recommend CBO for scaling proven winners and ABO for controlled testing.

    A segment that already carries proven tracking links / winning hypotheses is a
    scaling candidate (CBO lets Meta shift budget to the best ad set). A fresh test
    segment uses ABO so each ad set gets a guaranteed, equal learning budget.
    """
    is_test = not (segment.get("landingPageUrl") and segment.get("telegramBotUrl"))
    if is_test:
        return {
            "mode": "ABO",
            "rationale": (
                "Use ABO (ad-set budget optimization) for this test segment so each audience/creative ad set "
                "gets a guaranteed, equal learning budget and the comparison stays clean."
            ),
        }
    return {
        "mode": "CBO",
        "rationale": (
            "Use CBO (campaign budget optimization) when scaling this proven segment so Meta can shift budget "
            "toward the best-performing ad set automatically."
        ),
    }


def choose_placements(segment: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    requested = [normalize_placement(item) for item in segment.get("placements", []) if item]
    requested = [item for item in requested if item]
    if not requested:
        requested = SHAHLO_PLACEMENT_PRIORITY.copy()

    ranked_labels = " ".join(item.get("label", "").lower() for item in analysis.get("placements", [])[:5])
    preferred = [item for item in requested if item in SHAHLO_PLACEMENT_PRIORITY]
    if "instagram" in ranked_labels and preferred:
        return preferred
    if preferred:
        return preferred
    return [item for item in SHAHLO_PLACEMENT_PRIORITY if item not in WEAK_COLD_PLACEMENTS]


def choose_interests(segment: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    selected = list(dict.fromkeys([str(item) for item in segment.get("interests", []) if item]))
    ranked = [
        item.get("label")
        for item in analysis.get("audience", {}).get("interests", [])
        if item.get("label")
    ]
    combined = list(dict.fromkeys(selected + ranked[:4]))
    if combined:
        return combined[:6]
    return ["Artificial intelligence", "Digital marketing", "Online education"]


def build_geo_strategy(locations: list[str], analysis: dict[str, Any]) -> dict[str, Any]:
    top_region = first_label(analysis.get("audience", {}).get("regions", []))
    broad_country = any(str(location).lower() in {"uzbekistan", "uz"} for location in locations)
    recommendation = (
        "Start with country-level Uzbekistan and use Tashkent as a controlled challenger."
        if broad_country
        else "Use this city/region test as a challenger against country-level Uzbekistan."
    )
    return {
        "locations": locations,
        "recommendation": recommendation,
        "watchlist": [region for region in [top_region, "Tashkent"] if region],
    }


def build_creative_angles(segment: dict[str, Any]) -> list[str]:
    angle = str(segment.get("offerAngle") or "").lower()
    base = [
        "Shahlo split-screen teaching format: face below, workflow/proof above, soft CTA to watch the free video.",
        "Visual-first AI output format: strong AI commercial/cartoon/avatar result in the first three seconds.",
        "Proof-led version: student contract, student work, or authority clip before the free-video CTA.",
    ]
    if "business" in angle or "automation" in angle:
        base.insert(0, "Business owner/SMM angle: show how AI visuals and automations increase service value.")
    elif "income" in angle or "earn" in angle:
        base.insert(0, "Income angle: product commercial videos for brands as the clearest money path.")
    return base[:4]


def funnel_readiness(segment: dict[str, Any]) -> dict[str, Any]:
    missing = []
    if not segment.get("landingPageUrl"):
        missing.append("landing_page")
    if not segment.get("telegramBotUrl"):
        missing.append("telegram_bot")
    return {
        "status": "ready" if not missing else "needs_links",
        "missing": missing,
        "trackingPlan": "Append visitor_id to Telegram start links and save every bot step as a flexible funnel event.",
    }


def build_risks(
    segments: list[dict[str, Any]],
    analysis: dict[str, Any],
    estimated_leads: float,
    capacity: float,
) -> list[str]:
    risks = []
    if capacity and estimated_leads > capacity:
        risks.append(
            f"Estimated lead load ({estimated_leads:g}/day) is above sales capacity ({capacity:g}/day); throttle budget or route only qualified segments."
        )
    if any(segment["funnelReadiness"]["status"] != "ready" for segment in segments):
        risks.append("Some segments are missing landing or Telegram links, so downstream quality tracking is not complete yet.")
    if as_float(analysis.get("summary", {}).get("purchases"), 0) == 0:
        risks.append("Purchase attribution is missing; strategy must treat Telegram START and qualified lead as proxy metrics.")
    if any("facebook" in placement for segment in segments for placement in segment["recommendedPlacements"]):
        risks.append("Facebook cold placement is still present; validate it separately because Uzbekistan conversion quality is usually stronger on Instagram.")
    return risks


def build_summary(
    playbook: dict[str, Any],
    analysis: dict[str, Any],
    segments: list[dict[str, Any]],
    total_budget: float,
) -> str:
    best_placement = first_label(strategy_placement_evidence(analysis)) or "Instagram Reels/Stories/Feed"
    best_interest = first_label(analysis.get("audience", {}).get("interests", [])) or "AI and digital marketing"
    return (
        f"Launch {len(segments)} configurable segment test(s) with ${total_budget:,.0f}/day, "
        f"optimize for {playbook.get('primarySuccessMetric', 'telegram_start')}, and use {best_placement} plus {best_interest} as the first evidence-backed hypotheses."
    )


def build_test_matrix(
    segments: list[dict[str, Any]],
    playbook: dict[str, Any],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    primary = playbook.get("primarySuccessMetric", "telegram_start")
    matrix = [
        {
            "day": "Day 0",
            "test": "Tracking readiness",
            "decisionMetric": "visitor_id -> Telegram START match rate",
            "action": "Verify every live landing page and bot link emits flexible funnel events before scaling.",
        },
        {
            "day": "Days 1-2",
            "test": "Placement quality",
            "decisionMetric": primary,
            "action": "Run Instagram Reels, Stories, and Feed as the main cold placement set; keep weak placements out of the first learning test.",
        },
        {
            "day": "Days 2-4",
            "test": "Audience purchasing power",
            "decisionMetric": "qualified lead rate and sales feedback",
            "action": "Compare employee/second-income and business-owner segments against cheap-volume segments.",
        },
    ]
    if segments:
        matrix.append({
            "day": "Days 4-5",
            "test": "Creative angle rotation",
            "decisionMetric": "cost per qualified Telegram START",
            "action": f"Give each segment at least {max(3, min(10, len(segments) * 3))} creatives before pausing low-quality click drivers.",
        })
    if first_label(analysis.get("audience", {}).get("regions", [])):
        matrix.append({
            "day": "Days 5-7",
            "test": "Geo challenger",
            "decisionMetric": "CPL, Telegram START rate, sales quality",
            "action": "Test Tashkent or the top saved region against broad Uzbekistan only after the broad campaign has baseline data.",
        })
    return matrix


def build_approval_actions(
    segments: list[dict[str, Any]],
    risks: list[str],
    playbook: dict[str, Any],
) -> list[dict[str, Any]]:
    actions = [
        {
            "id": "approve-launch-structure",
            "title": "Approve launch structure",
            "impact": f"Prepare {len(segments)} segment test(s) using {playbook.get('primarySuccessMetric', 'telegram_start')} as the first optimization signal.",
            "risk": "medium",
            "owner": "human",
            "status": "needs_review",
        },
        {
            "id": "approve-instagram-first-placement",
            "title": "Approve Instagram-first placements",
            "impact": "Prioritize Reels, Stories, and Feed for cold traffic; use Facebook only as a separated test or retargeting candidate.",
            "risk": "low",
            "owner": "human",
            "status": "needs_review",
        },
        {
            "id": "approve-monitoring-rules",
            "title": "Approve monitoring rules",
            "impact": "Monitor every four hours and ask for approval before pausing, scaling, or changing audiences.",
            "risk": "low",
            "owner": "human",
            "status": "needs_review",
        },
    ]
    if risks:
        actions.append({
            "id": "resolve-launch-risks",
            "title": "Resolve launch risks",
            "impact": risks[0],
            "risk": "high",
            "owner": "human",
            "status": "needs_review",
        })
    return actions


def build_knowledge_used(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "bestPlacements": [item.get("label") for item in strategy_placement_evidence(analysis)[:5] if item.get("label")],
        "bestInterests": [
            item.get("label")
            for item in analysis.get("audience", {}).get("interests", [])[:5]
            if item.get("label")
        ],
        "bestRegions": [
            item.get("label")
            for item in analysis.get("audience", {}).get("regions", [])[:5]
            if item.get("label")
        ],
        "lessons": analysis.get("lessons", [])[:5],
        "recommendations": analysis.get("recommendations", [])[:5],
    }


def build_launch_packet(strategy: dict[str, Any], playbook: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": "approval_required",
        "primaryGoal": playbook.get("primarySuccessMetric", "telegram_start"),
        "audiencePlan": [
            {
                "segmentId": segment["id"],
                "segmentName": segment["name"],
                "hypothesis": segment["audienceHypothesis"],
                "ageRange": segment["ageRange"],
                "gender": segment["gender"],
                "locations": segment["geoStrategy"]["locations"],
                "interests": segment["interestStrategy"],
                "scaleCondition": "Scale only after Telegram START quality and CRM lead quality hold for the monitoring window.",
            }
            for segment in strategy.get("segments", [])
        ],
        "creativePlan": [
            {
                "segmentId": segment["id"],
                "segmentName": segment["name"],
                "angles": segment["creativeAngles"],
                "replicate": "Proof-led Shahlo teaching/workflow videos and strong AI visual hooks.",
                "avoid": "Viral curiosity creatives that generate registrations without buyer-quality proof.",
            }
            for segment in strategy.get("segments", [])
        ],
        "placementPlan": {
            "use": list(dict.fromkeys(placement for segment in strategy.get("segments", []) for placement in segment.get("recommendedPlacements", []))),
            "avoid": launch_packet_avoid_placements(analysis),
            "rule": "Keep Instagram placements separated from Facebook tests until downstream buyer quality is proven.",
        },
        "funnelPlan": {
            "readiness": "ready" if all(segment["funnelReadiness"]["status"] == "ready" for segment in strategy.get("segments", [])) else "needs_links",
            "requiredEvents": [
                "landing_page_view",
                "landing_button_click",
                "telegram_start",
                "bot_step",
                "crm_form_submit",
                "crm_stage_change",
                "payment",
            ],
            "risks": strategy.get("risks", []),
        },
        "experimentPlan": strategy.get("testMatrix", []),
        "monitoringPlan": {
            "cadenceHours": 4,
            "watchMetrics": ["CPC", "CPL", "landing visit rate", "landing lead rate", "Telegram START rate", "CRM qualified rate"],
            "approvalRule": "Monitoring can recommend pauses, budget changes, and creative rotations, but execution requires approval.",
        },
        "approvalPlan": {
            "required": True,
            "actions": strategy.get("approvalActions", []),
            "publishBlocked": True,
        },
        "regressionChecklist": [
            "Dashboard loads and primary tabs render.",
            "Meta knowledge base is available or missing state is explicit.",
            "Agent chat routes to orchestrator, audience, creative, placement, funnel, monitoring, experiment, Meta AI, and execution agents.",
            "Campaign proposal remains review-only and paused.",
            "Approval queue blocks live Meta writes until approved.",
            "Dry-run execution never sends Meta write requests.",
            "Telegram command endpoint accepts natural-language tasks with the configured secret.",
            "Monitoring run stores alerts and does not execute changes.",
            "Funnel tracking keeps visitor_id and telegram_user_id requirements visible.",
            "Build, lint, backend tests, frontend tests, and e2e smoke test pass.",
        ],
    }


def launch_packet_avoid_placements(analysis: dict[str, Any]) -> list[str]:
    avoid = []
    for item in analysis.get("placements", []):
        label = str(item.get("label") or "").lower()
        if any(word in label for word in ["facebook", "audience_network", "messenger"]):
            avoid.append(label.replace(" / ", "_").replace(" ", "_"))
    return avoid or ["facebook_feed", "audience_network"]


def strategy_placement_evidence(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    placements = analysis.get("placements", [])
    instagram = [item for item in placements if "instagram" in str(item.get("label", "")).lower()]
    return instagram or placements


def recommended_age_range(analysis: dict[str, Any]) -> str:
    label = first_label(analysis.get("audience", {}).get("ageGender", []))
    if label and "/" in label:
        return label.split("/", maxsplit=1)[0].strip()
    return "23-45"


def infer_audience_hypothesis(segment: dict[str, Any]) -> str:
    text = f"{segment.get('name', '')} {segment.get('description', '')}".lower()
    if "business" in text:
        return "Small business owners, SMM agencies, and operators with higher purchasing power."
    if "creator" in text or "video" in text:
        return "Content creators and video editors who can monetize AI content skills."
    return "Full-time employees and motivated second-income seekers with enough purchasing power."


def normalize_placement(value: str) -> str:
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "instagram_reel": "instagram_reels",
        "ig_reels": "instagram_reels",
        "ig_stories": "instagram_stories",
        "ig_feed": "instagram_feed",
        "facebook_feeds": "facebook_feed",
    }
    return aliases.get(text, text)


def first_label(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        if item.get("label"):
            return str(item["label"])
    return None


def slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_") or "segment"


def as_float(value: Any, default: float = 0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default

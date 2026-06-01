from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .meta_execution import build_campaign_creation_approval
from .strategy_generator import generate_launch_strategy


def build_draft_campaign_proposal(
    playbook: dict[str, Any],
    knowledge: dict[str, Any] | None,
    *,
    account_id: str,
) -> dict[str, Any]:
    strategy = generate_launch_strategy(playbook, knowledge)
    approval = build_campaign_creation_approval(
        playbook,
        account_id=account_id,
        reason="Prepare a paused campaign proposal for review. Do not publish or spend.",
    )
    return {
        "id": f"proposal_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "mode": "review_only",
        "requiresApproval": True,
        "publishBlocked": True,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "playbookId": playbook.get("id"),
        "playbookName": playbook.get("name"),
        "strategyId": strategy["id"],
        "draftCampaign": approval["after"]["campaign"],
        "draftAdSets": approval["after"]["adsets"],
        "recommendedAudiences": build_recommended_audiences(strategy),
        "recommendedPlacements": build_recommended_placements(strategy),
        "avoidPlacements": build_avoid_placements(knowledge),
        "budgetPlan": strategy["budget"],
        "trackingReadiness": build_tracking_readiness(strategy),
        "approvalPacket": approval,
        "operatorChecklist": build_operator_checklist(strategy, approval),
        "evidence": strategy.get("knowledgeUsed", {}),
    }


def build_recommended_audiences(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for segment in strategy.get("segments", []):
        rows.append(
            {
                "segmentId": segment["id"],
                "segmentName": segment["name"],
                "audienceHypothesis": segment["audienceHypothesis"],
                "ageRange": segment["ageRange"],
                "gender": segment["gender"],
                "locations": segment["geoStrategy"]["locations"],
                "interestStrategy": segment["interestStrategy"],
                "confidence": "medium" if segment["funnelReadiness"]["status"] == "ready" else "needs_tracking",
            }
        )
    return rows


def build_recommended_placements(strategy: dict[str, Any]) -> list[str]:
    placements: list[str] = []
    for segment in strategy.get("segments", []):
        placements.extend(segment.get("recommendedPlacements", []))
    return list(dict.fromkeys(placements))


def build_avoid_placements(knowledge: dict[str, Any] | None) -> list[str]:
    analysis = (knowledge or {}).get("analysis", {})
    weak = []
    for item in analysis.get("placements", []):
        label = str(item.get("label") or "").lower()
        quality_score = float(item.get("qualityScore") or 0)
        if ("facebook" in label or "audience_network" in label) and quality_score < 45:
            weak.append(label.replace(" / ", "_").replace(" ", "_"))
    return weak or ["facebook_feed", "audience_network"]


def build_tracking_readiness(strategy: dict[str, Any]) -> dict[str, Any]:
    missing = [
        {
            "segmentId": segment["id"],
            "segmentName": segment["name"],
            "missing": segment["funnelReadiness"]["missing"],
        }
        for segment in strategy.get("segments", [])
        if segment["funnelReadiness"]["missing"]
    ]
    return {
        "status": "ready" if not missing else "needs_links",
        "missing": missing,
        "requiredEvents": [
            "landing_page_view",
            "landing_button_click",
            "telegram_start",
            "bot_step",
            "crm_form_submit",
        ],
    }


def build_operator_checklist(strategy: dict[str, Any], approval: dict[str, Any]) -> list[str]:
    checklist = [
        "Confirm every segment has a named VSL, landing page, Telegram bot, and visitor_id tracking path.",
        "Confirm the generated campaign and ad sets are PAUSED before approval.",
        "Confirm the total daily budget is inside the configured max budget.",
        "Review top audience, placement, and creative assumptions before creating drafts.",
        "Approve the packet only after tracking and sales-capacity risks are understood.",
    ]
    if strategy.get("risks"):
        checklist.append(f"Resolve launch risk: {strategy['risks'][0]}")
    if approval.get("guardrailResult") == "fail":
        checklist.append("Do not execute until failed guardrails are fixed.")
    return checklist

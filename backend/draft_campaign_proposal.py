from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .analysis_engine import rank_audiences_for_next_campaign
from .meta_execution import build_campaign_creation_approval
from .strategy_generator import generate_launch_strategy

try:  # Optional: recent-playbook exclusion degrades gracefully if storage is unavailable.
    from .playbook_store import load_playbooks
except Exception:  # pragma: no cover - defensive import guard
    load_playbooks = None  # type: ignore[assignment]


def build_draft_campaign_proposal(
    playbook: dict[str, Any],
    knowledge: dict[str, Any] | None,
    *,
    account_id: str,
) -> dict[str, Any]:
    strategy = generate_launch_strategy(playbook, knowledge)
    analysis = (knowledge or {}).get("analysis", {}) or {}
    # Pick the template = best ranked campaign that actually carries a config block, so a
    # proposed test inherits the objective/optimization/bid/budget-mode that already wins
    # on this account. None when no winner has config -> the live-validated defaults apply.
    source_template = select_source_template(analysis)
    template_config = source_template.get("config") if source_template else None

    approval = build_campaign_creation_approval(
        playbook,
        account_id=account_id,
        reason="Prepare a paused campaign proposal for review. Do not publish or spend.",
        knowledge=knowledge,
        template=template_config,
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
        # recommendedAudiences keeps its existing list shape (frontend contract). The new
        # "top 3 audiences to run next" lives in the additive recommendedAudiencesTopThree
        # field so nothing existing changes shape.
        "recommendedAudiences": build_recommended_audiences(strategy),
        "recommendedAudiencesTopThree": build_top_three_audiences(analysis, playbook),
        "recommendedPlacements": build_recommended_placements(strategy),
        "avoidPlacements": build_avoid_placements(knowledge),
        "budgetPlan": strategy["budget"],
        "sourceTemplate": source_template,
        "trackingReadiness": build_tracking_readiness(strategy),
        "approvalPacket": approval,
        "operatorChecklist": build_operator_checklist(strategy, approval),
        "evidence": strategy.get("knowledgeUsed", {}),
    }


def select_source_template(analysis: dict[str, Any]) -> dict[str, Any] | None:
    """Best ranked campaign carrying a non-empty config block, described for the operator.

    topCampaigns is already quality-ranked upstream, so the first entry whose config has
    at least one real (non-null) field is the proven winner to mirror. Returns None when
    no campaign carries config (partial/synthetic knowledge), so defaults stay in force.
    """
    for campaign in analysis.get("topCampaigns", []) or []:
        config = campaign.get("config") or {}
        if any(value not in (None, "", [], {}) for value in config.values()):
            keys = campaign.get("keys", {}) or {}
            return {
                "sourceCampaignId": keys.get("campaign_id"),
                "sourceCampaignName": keys.get("campaign_name") or campaign.get("label"),
                "config": config,
            }
    return None


def recent_playbook_interest_labels(playbook: dict[str, Any]) -> list[str]:
    """Interests already used by recent playbooks + the current one, so suggestions skip
    audiences we have already tested. Defensive: empty list if storage is unavailable."""
    labels: list[str] = []

    def collect(book: dict[str, Any]) -> None:
        for segment in book.get("segments", []) or []:
            for interest in segment.get("interests", []) or []:
                if interest:
                    labels.append(str(interest))

    collect(playbook or {})
    if load_playbooks is not None:
        try:
            for book in load_playbooks()[:5]:
                collect(book)
        except Exception:  # pragma: no cover - storage best-effort
            pass
    return list(dict.fromkeys(labels))


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


def build_top_three_audiences(
    analysis: dict[str, Any] | None,
    playbook: dict[str, Any] | None,
) -> dict[str, Any]:
    """The additive "top 3 audiences to run next", excluding recently-tested interests."""
    exclude_labels = recent_playbook_interest_labels(playbook or {})
    audiences = rank_audiences_for_next_campaign(analysis or {}, exclude_labels=exclude_labels, n=3)
    return {
        "audiences": audiences,
        "excludedRecentlyTested": exclude_labels,
    }


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

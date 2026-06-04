"""Agent registry, strategy council, system checklist, and dashboard chat routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from ..agent_council import run_strategy_council, should_run_strategy_council
from ..agent_orchestrator import (
    agent_registry,
    build_agent_decision,
    build_agent_handoffs,
    orchestrate_agent_chat,
    route_question,
)
from ..agent_quality import evaluate_agent_response
from ..api_models import ChatRequest, ChatResponse, CouncilRequest
from ..approval_store import list_approval_requests
from ..campaign_specific_analysis import campaign_specific_answer
from ..dashboard_service import (
    answer_audiences,
    answer_creatives,
    answer_experiments,
    answer_from_knowledge_base,
    answer_funnel,
    answer_meta_status,
    answer_monitoring,
    answer_placements,
    answer_summary,
    build_dashboard,
    default_questions,
    knowledge_chat_preview,
)
from ..agent_personas import specialist_system_prompt
from ..knowledge_base import load_knowledge_base
from ..llm_reasoner import generate_chat_answer, generate_specialist_answer, refine_text
from ..monitoring_scheduler import list_monitoring_runs
from ..playbook_store import load_playbooks, save_playbook
from ..proactive_insights import build_proactive_insights
from ..system_checklist import build_system_checklist
from .meta import meta_status

router = APIRouter()

_PROACTIVE_MARKERS = (
    "what should i do",
    "what should we do",
    "what should we improve",
    "what can we improve",
    "find improvements",
    "biggest opportunities",
    "proactive insight",
    "proactive recommendation",
    "what are the opportunities",
    "where are we wasting",
)


def is_proactive_request(lower_question: str) -> bool:
    return any(marker in lower_question for marker in _PROACTIVE_MARKERS)


def format_proactive_insights(insights: list[dict[str, Any]]) -> str:
    if not insights:
        return (
            "No high-priority issues stand out in the saved data right now. "
            "Sync fresh Meta data, then ask again and I will flag creative fatigue, placement waste, and funnel leaks proactively."
        )
    lines = ["Proactive recommendations from your saved Meta data (highest priority first):", ""]
    for insight in insights[:6]:
        lines.append(f"- [{insight['priority']}] ({insight['agent']}) {insight['title']}: {insight['detail']}")
        lines.append(f"  Suggested action: {insight['suggestedAction']}")
    lines.append("")
    lines.append("These are recommendations only — I will not change anything in Meta without approval.")
    return "\n".join(lines)


@router.get("/api/agent/insights")
def agent_insights() -> dict[str, Any]:
    return {"insights": build_proactive_insights(load_knowledge_base())}


def agent_status_payload(agent: dict[str, Any], knowledge: dict[str, Any] | None, live_writes_enabled: bool) -> dict[str, Any]:
    agent_id = str(agent.get("id") or "")
    blocked_reasons = []
    if agent_id in {"audit", "audience", "creative", "placement", "funnel", "monitoring", "experiment"} and not knowledge:
        blocked_reasons.append("knowledge_base_missing")
    if agent_id in {"execution", "browser_operator"} and not live_writes_enabled:
        blocked_reasons.append("live_writes_disabled")
    if agent_id == "browser_operator":
        blocked_reasons.append("browser_fallback_requires_specific_approved_action")
    readiness = "blocked" if blocked_reasons and agent_id in {"execution", "browser_operator"} else "needs_data" if blocked_reasons else "ready"
    return {
        **agent,
        "readinessStatus": readiness,
        "blockedReasons": blocked_reasons,
        "lastVerifiedBy": "automated_backend_tests",
    }


@router.get("/api/agents")
def agents() -> dict[str, Any]:
    live_writes_enabled = os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true"
    knowledge = load_knowledge_base()
    return {
        "agents": [agent_status_payload(agent, knowledge, live_writes_enabled) for agent in agent_registry().values()],
        "executionEnabled": live_writes_enabled,
        "approvalRequiredForLiveChanges": True,
        "liveWriteScope": "paused_campaign_and_adset_creation_only" if live_writes_enabled else "disabled",
    }


@router.post("/api/agent/council")
def agent_council(request: CouncilRequest) -> dict[str, Any]:
    council = run_strategy_council(
        request.message.strip() or "Run strategy council for the next Meta campaign.",
        knowledge=load_knowledge_base(),
        playbooks=load_playbooks(),
    )
    return {"ok": True, "council": council}


@router.get("/api/system/checklist")
def system_checklist() -> dict[str, Any]:
    return build_system_checklist(
        agents=list(agent_registry().values()),
        knowledge=load_knowledge_base(),
        approvals=list_approval_requests(),
        monitoring_runs=list_monitoring_runs(),
    )



def specialist_chat_response(
    question: str,
    *,
    answer: str,
    sources: list[str],
    suggestedQuestions: list[str],
    extra: dict[str, Any] | None = None,
) -> ChatResponse:
    routed = route_question(question)
    payload: dict[str, Any] = {
        "answer": answer,
        "sources": sources,
        "suggestedQuestions": suggestedQuestions,
        "activeAgent": routed["agentId"],
        "routeReason": routed["reason"],
        "agentHandoffs": build_agent_handoffs(routed["agentId"]),
    }
    payload["agentDecision"] = build_agent_decision(routed, payload)
    payload["quality"] = evaluate_agent_response(payload)
    if extra:
        payload.update(extra)
    return ChatResponse(**payload)


def format_council_answer(council: dict[str, Any]) -> str:
    final_plan = council.get("finalPlan", {})
    audience = final_plan.get("audienceDecision", {})
    creative = final_plan.get("creativeDecision", {})
    placement = final_plan.get("placementDecision", {})
    execution = final_plan.get("executionDecision", {})
    return "\n".join(
        [
            "Strategy Council completed. The agents talked through initial recommendations, challenged each other, and produced one approval-safe campaign plan.",
            "",
            f"Council quality: {council.get('averageScoreOutOf10', 0)}/10 across {len(council.get('agents', []))} agents and {len(council.get('events', []))} agent-to-agent exchanges.",
            "",
            f"Audience: start with {audience.get('primary', 'the strongest validated audience evidence')} and validate every segment against Telegram START and CRM quality.",
            f"Creative: use {creative.get('topCreative', 'the top historical VSL creative')} first, but qualify buyer intent earlier with proof and course value.",
            f"Placement: use {placement.get('primary', 'Instagram Reels/Stories/Feed')} as the primary hypothesis and isolate weak cheap placements.",
            f"Execution: paused draft creation is {bool(execution.get('canCreatePausedDraft', True))}; publishing is blocked until approval.",
            "",
            "I will not publish or activate spend from this council plan. The next safe action is a paused campaign draft or approval request.",
        ]
    )




@router.post("/api/agent/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest) -> ChatResponse:
    question = request.message.strip()
    if not question:
        return ChatResponse(
            answer="Ask me about creatives, audiences, placements, funnel leaks, experiments, or Meta connection status.",
            sources=["agent"],
            suggestedQuestions=default_questions(),
        )

    lower = question.lower()
    routed = route_question(question)
    dashboard_data = build_dashboard()
    meta = await meta_status()
    knowledge = load_knowledge_base()
    if should_run_strategy_council(question):
        council = run_strategy_council(question, knowledge=knowledge, playbooks=load_playbooks())
        answer = await refine_text(
            format_council_answer(council),
            instruction="Sharpen this Meta strategy-council summary into a decisive, approval-safe recommendation. Keep every number and named entity.",
            context=council.get("finalPlan"),
        )
        return specialist_chat_response(
            question,
            answer=answer,
            sources=["agent_council", "strategy_generator", "storage/meta_knowledge_base.json", "docs/AGENT_OPERATING_POLICY.md"],
            suggestedQuestions=[
                "Create the paused campaign draft from this council plan.",
                "Which council agent had the weakest assumption?",
                "What should the next critique round challenge?",
            ],
            extra={
                "agentCouncil": council,
                "generatedPlaybook": council.get("generatedPlaybook"),
                "generatedStrategy": council.get("generatedStrategy"),
            },
        )

    if is_proactive_request(lower) and knowledge:
        insights = build_proactive_insights(knowledge)
        answer = await refine_text(
            format_proactive_insights(insights),
            instruction="Rewrite these proactive Meta ad recommendations to be concise and decisive. Keep every number, agent, and the approval-safety note.",
            context=insights,
        )
        return specialist_chat_response(
            question,
            answer=answer,
            sources=["proactive_insights", "storage/meta_knowledge_base.json"],
            suggestedQuestions=[
                "Turn the top recommendation into an experiment.",
                "Which placement is wasting budget?",
                "What tracking is missing before we scale?",
            ],
            extra={"proactiveInsights": insights},
        )

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

    if routed["agentId"] == "monitoring":
        return specialist_chat_response(
            question,
            answer=answer_monitoring(dashboard_data),
            sources=["monitoring", "alerts", "approvalActions"],
            suggestedQuestions=[
                "What should we check every four hours?",
                "Which alert should become an experiment?",
                "What should require approval before execution?",
            ],
        )

    if routed["agentId"] == "experiment":
        return specialist_chat_response(
            question,
            answer=answer_experiments(dashboard_data),
            sources=["experiments", "approvalActions"],
            suggestedQuestions=[
                "What should the stop rule be?",
                "What should the scale rule be?",
                "Which variable should we test first?",
            ],
        )

    if knowledge:
        campaign_answer = campaign_specific_answer(question, knowledge)
        if campaign_answer:
            return specialist_chat_response(
                question,
                answer=campaign_answer,
                sources=["campaign_specific_analysis", "storage/meta_knowledge_base.json"],
                suggestedQuestions=[
                    "Rank creatives for this campaign.",
                    "Which ad set should become the scale candidate?",
                    "What tracking is missing before scaling?",
                ],
            )
        # Inverted LLM path: the routed specialist reasons with its own persona +
        # house strategy (grounded), instead of the model always speaking as a
        # generic auditor. Falls back to the generic prompt only when the routed
        # agent has no persona, and to deterministic templates below on any miss.
        persona_prompt = specialist_system_prompt(routed["agentId"])
        llm_answer: str | None = None
        try:
            if persona_prompt:
                llm_answer = await generate_specialist_answer(
                    question,
                    knowledge_chat_preview(knowledge),
                    system_prompt=persona_prompt,
                )
            else:
                generic = await generate_chat_answer(question, knowledge_chat_preview(knowledge))
                llm_answer = None if (not generic or generic.startswith("LLM chat unavailable")) else generic
        except Exception:
            llm_answer = None
        if llm_answer:
            return specialist_chat_response(
                question,
                answer=llm_answer,
                sources=["storage/meta_knowledge_base.json", "openai", routed["agentId"]],
                suggestedQuestions=[
                    "Which audience should we scale?",
                    "How is lead percentage calculated?",
                    "What should we test next?",
                ],
            )
        kb_answer = answer_from_knowledge_base(lower, knowledge)
        if kb_answer:
            return specialist_chat_response(
                question,
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
        return specialist_chat_response(
            question,
            answer=answer_creatives(dashboard_data),
            sources=["creativeAnalyses", "metrics"],
            suggestedQuestions=[
                "Which creative should we replicate?",
                "Why did the viral creative not convert?",
                "What creative should we test next?",
            ],
        )

    if any(word in lower for word in ["audience", "age", "buyer", "purchasing", "target"]):
        return specialist_chat_response(
            question,
            answer=answer_audiences(dashboard_data),
            sources=["audience", "metrics"],
            suggestedQuestions=[
                "Which audience should we scale?",
                "Which audience has weak purchasing power?",
                "What targeting should we test next?",
            ],
        )

    if any(word in lower for word in ["placement", "facebook", "instagram", "reels", "feed"]):
        return specialist_chat_response(
            question,
            answer=answer_placements(dashboard_data),
            sources=["placements", "metrics"],
            suggestedQuestions=[
                "Should we turn off Facebook Feed?",
                "Which placement is best for buyers?",
                "How should we split placement budget?",
            ],
        )

    if any(word in lower for word in ["funnel", "telegram", "landing", "webinar", "lead", "leak"]):
        return specialist_chat_response(
            question,
            answer=answer_funnel(dashboard_data),
            sources=["funnel", "trackingHealth"],
            suggestedQuestions=[
                "Where is the biggest funnel leak?",
                "How can we improve Telegram join rate?",
                "Which funnel metric should we watch daily?",
            ],
        )

    if any(word in lower for word in ["monitor", "alert", "attention", "trend", "rising", "improving", "getting expensive"]):
        return specialist_chat_response(
            question,
            answer=answer_monitoring(dashboard_data),
            sources=["monitoring", "alerts", "approvalActions"],
            suggestedQuestions=[
                "What should we check every four hours?",
                "Which alert should become an experiment?",
                "What should require approval before execution?",
            ],
        )

    if any(word in lower for word in ["experiment", "test", "budget", "scale", "pause", "recommend"]):
        return specialist_chat_response(
            question,
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

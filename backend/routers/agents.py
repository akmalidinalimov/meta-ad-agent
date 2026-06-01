"""Agent registry + dashboard chat routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from ..agent_orchestrator import (
    agent_registry,
    build_agent_handoffs,
    orchestrate_agent_chat,
    route_question,
)
from ..agent_quality import evaluate_agent_response
from ..api_models import ChatRequest, ChatResponse
from ..dashboard_service import (
    answer_audiences,
    answer_creatives,
    answer_experiments,
    answer_from_knowledge_base,
    answer_funnel,
    answer_meta_status,
    answer_placements,
    answer_summary,
    build_dashboard,
    default_questions,
    knowledge_chat_preview,
)
from ..knowledge_base import load_knowledge_base
from ..llm_reasoner import generate_chat_answer
from ..playbook_store import load_playbooks, save_playbook
from .meta import meta_status

router = APIRouter()


@router.get("/api/agents")
def agents() -> dict[str, Any]:
    live_writes_enabled = os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true"
    return {
        "agents": list(agent_registry().values()),
        "executionEnabled": live_writes_enabled,
        "approvalRequiredForLiveChanges": True,
        "liveWriteScope": "paused_campaign_and_adset_creation_only" if live_writes_enabled else "disabled",
    }


def specialist_chat_response(
    question: str,
    *,
    answer: str,
    sources: list[str],
    suggestedQuestions: list[str],
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
    payload["quality"] = evaluate_agent_response(payload)
    return ChatResponse(**payload)


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
    dashboard_data = build_dashboard()
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
            return specialist_chat_response(
                question,
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

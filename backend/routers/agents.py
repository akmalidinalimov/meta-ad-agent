"""Agent registry, strategy council, system checklist, and dashboard chat routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..agent_council import run_strategy_council, should_run_strategy_council
from ..config import live_writes_enabled
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
from ..campaign_specific_analysis import (
    campaign_configuration_answer,
    campaign_roster_answer,
    campaign_specific_answer,
)
from ..execution_service import apply_live_sync, auto_execute_paused
from ..meta_live import get_live_account
from ..pending_context_store import (
    clear_pending,
    get_pending,
    merge_refinement,
    operator_key,
    set_pending,
)
from .. import approval_store
from ..dashboard_service import (
    answer_audiences,
    answer_budget_pacing,
    answer_creatives,
    answer_experiments,
    answer_from_knowledge_base,
    answer_funnel,
    answer_landing_cro,
    answer_measurement,
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
    if agent_id in {"audit", "audience", "creative", "placement", "funnel", "monitoring", "experiment", "measurement", "budget_pacing", "landing_cro"} and not knowledge:
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
    writes_enabled = live_writes_enabled()
    knowledge = load_knowledge_base()
    return {
        "agents": [agent_status_payload(agent, knowledge, writes_enabled) for agent in agent_registry().values()],
        "executionEnabled": writes_enabled,
        "approvalRequiredForLiveChanges": True,
        "liveWriteScope": "paused_campaign_and_adset_creation_only" if writes_enabled else "disabled",
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




# Informational questions ("what campaigns are active?", "which audience is best?")
# must be answered from the account data by the LLM, NOT handed to the orchestrator,
# which replies with generic campaign-creation / agent-description text. The orchestrator
# only runs when the message expresses an explicit create/change action.
_QUESTION_STARTERS = (
    "what", "which", "why", "how", "who", "when", "where", "is ", "are ", "do ", "does ",
    "can ", "show", "list", "tell me", "explain", "compare", "summarize", "summarise",
)
_ACTION_WORDS = (
    "create", "build", "launch", "set up", "setup", "draft", "make a", "make me", "plan a",
    "generate a", "rename", "pause", "resume", "turn off", "turn on", "increase", "decrease",
    "raise the", "lower the", "duplicate", "set budget", "change the budget", "prepare a",
    "prepare the", "scale up", "scale the",
    # Bulk-manage verbs so "delete/archive/clean up the old campaigns" reaches the orchestrator.
    "delete", "remove", "archive", "clean up", "clear out", "get rid", "stop", "disable",
    "deactivate",
)
# The orchestrator legitimately *describes* these agents/workflows for questions about
# the agent system itself; only those keep using it for non-action questions.
_ORCHESTRATOR_INFO_AGENTS = {"meta_ai_advisor", "meta_ai_strategist", "execution"}
_AGENT_SYSTEM_WORDS = ("sub-agent", "subagent", "agent role", "orchestrator", "specialist")


def _wants_action(lower: str) -> bool:
    stripped = lower.strip()
    if stripped.endswith("?") or stripped.startswith(_QUESTION_STARTERS):
        return False
    return any(word in lower for word in _ACTION_WORDS)


def _should_run_orchestrator(lower: str, routed: dict) -> bool:
    return (
        _wants_action(lower)
        or routed.get("agentId") in _ORCHESTRATOR_INFO_AGENTS
        or any(word in lower for word in _AGENT_SYSTEM_WORDS)
    )


def _ads_manager_link(account_id: str | None) -> str | None:
    """Deep link to the account's Ads Manager (campaigns view), or None when unknown."""
    if not account_id:
        return None
    acct = account_id[4:] if str(account_id).startswith("act_") else str(account_id)
    return f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={acct}"


def _created_summary(created: list[dict[str, Any]]) -> str:
    """One-line count of created PAUSED objects, e.g. '1 campaign, 3 ad sets, 15 ads'."""
    counts: dict[str, int] = {}
    for obj in created or []:
        level = str(obj.get("level") or "object")
        counts[level] = counts.get(level, 0) + 1
    labels = {"campaign": "campaign", "adset": "ad set", "ad": "ad"}
    parts = []
    for level in ("campaign", "adset", "ad"):
        n = counts.get(level, 0)
        if n:
            label = labels[level]
            parts.append(f"{n} {label}" + ("s" if n != 1 and not label.endswith("s") else ""))
    return ", ".join(parts) or "no objects"


def _append_autonomous_execution(answer: str, created: list[dict[str, Any]], account_id: str | None) -> str:
    """Append the created-PAUSED-objects summary + Ads Manager deep link to the answer."""
    lines = [
        answer,
        "",
        f"Created in Meta as PAUSED: {_created_summary(created)}. Nothing spends until you enable delivery.",
    ]
    link = _ads_manager_link(account_id)
    if link:
        lines.append(f"Review in Ads Manager: {link}")
    return "\n".join(lines)


_AFFIRMATIONS = (
    "approve",
    "approved",
    "yes",
    "go ahead",
    "do it",
    "confirm",
    "confirmed",
    "proceed",
    "ok do it",
    "okay do it",
    "yes do it",
)
_NEGATIONS = (
    "reject",
    "rejected",
    "cancel",
    "no",
    "stop",
    "don't",
    "dont",
    "do not",
    "nevermind",
    "never mind",
)


def _is_affirmation(text: str) -> bool:
    return text.strip().lower().rstrip("!.") in _AFFIRMATIONS


def _is_negation(text: str) -> bool:
    t = text.strip().lower().rstrip("!.")
    return t in _NEGATIONS


def resolve_pending_manage(op_key: str, message: str) -> dict[str, Any] | None:
    """Handle a typed approve/reject for an operator's pending bulk-manage approval.

    Shared by the web chat and the Telegram conversational path so "type approve" behaves
    identically on both surfaces. Returns a dict {answer, sources, suggestedQuestions}
    when it handled the message, or None when there's no pending manage / the message is
    neither an affirmation nor a negation (so normal routing continues).
    """
    pending = get_pending(op_key)
    if not pending or pending.get("kind") != "manage" or not pending.get("approvalId"):
        return None

    approval_id = pending["approvalId"]
    action = pending.get("action") or "manage"
    verb_past = "Archived" if action == "archive" else "Paused"

    if _is_affirmation(message):
        try:
            approval_store.approve_request(approval_id, approved_by="chat")
            result = apply_live_sync(approval_id)
        except Exception as error:  # noqa: BLE001 - surface as a message, not a 500
            clear_pending(op_key)
            return {
                "answer": f"I couldn't apply that: {error}",
                "sources": ["campaign_manage"],
                "suggestedQuestions": ["Try again.", "Show me the campaigns you created."],
            }
        clear_pending(op_key)
        if not result.get("ok"):
            return {
                "answer": (
                    f"I approved it but the Meta write was blocked: "
                    f"{result.get('error') or 'unknown error'}."
                ),
                "sources": ["campaign_manage"],
                "suggestedQuestions": ["Check live-write configuration.", "Try again."],
            }
        changed = (result.get("result") or {}).get("changed") or []
        errors = (result.get("result") or {}).get("errors") or []
        answer = f"✅ {verb_past} {len(changed)} campaign(s)."
        if errors:
            answer += f" {len(errors)} could not be updated."
        return {
            "answer": answer,
            "sources": ["campaign_manage", "meta_execution"],
            "suggestedQuestions": [
                "Show me the active campaigns.",
                "What should we scale next?",
                "Archive more old campaigns.",
            ],
        }

    if _is_negation(message):
        try:
            approval_store.reject_request(approval_id, rejected_by="chat", reason="Rejected from chat.")
        except Exception:  # noqa: BLE001 - rejection is best-effort
            pass
        clear_pending(op_key)
        return {
            "answer": "Cancelled. Nothing was changed.",
            "sources": ["campaign_manage"],
            "suggestedQuestions": [
                "Pause the idle campaigns you created.",
                "Show me the campaigns you created.",
            ],
        }

    return None


def _ad_account_id() -> str | None:
    try:
        from ..meta_client import get_meta_config

        return get_meta_config().ad_account_id or None
    except Exception:  # noqa: BLE001 - config absent in tests/dev
        return None


def _approval_total_daily_budget(approval: dict[str, Any]) -> float | None:
    adsets = (approval.get("after") or {}).get("adsets") or []
    total = sum(float(a.get("daily_budget") or 0) / 100 for a in adsets)
    return total or None


def _approval_audience_names(approval: dict[str, Any]) -> list[str]:
    adsets = (approval.get("after") or {}).get("adsets") or []
    return [str(a.get("name", "")).replace(" - DRAFT", "") for a in adsets if a.get("name")]


def _refine_pending_campaign(
    op_key: str,
    pending: dict[str, Any],
    overrides: dict[str, Any],
    knowledge: dict[str, Any] | None,
) -> ChatResponse | None:
    """Rebuild the operator's in-flight autonomous draft with refinement overrides,
    update the SAME approvalId in place, refresh the pending pointer, and return a
    "refined your draft" answer. Returns None if the rebuild fails."""
    from ..opportunity_finder import build_autonomous_campaign

    approval_id = pending["approvalId"]
    merged_budget = overrides.get("budget", pending.get("budget"))
    account_id, pixel_id = _ad_account_id(), None
    try:
        from ..meta_client import get_meta_config

        config = get_meta_config()
        account_id = config.ad_account_id or account_id
        pixel_id = config.pixel_id or None
    except Exception:  # noqa: BLE001 - config absent in tests/dev
        pass

    rebuilt = build_autonomous_campaign(
        knowledge,
        load_playbooks(),
        account_id=account_id,
        budget=merged_budget,
        n_audiences=3,
        n_creatives=5,
        pixel_id=pixel_id,
        approval_id=approval_id,
    )
    if rebuilt is None:
        return None

    saved = approval_store.update_approval_request(approval_id, rebuilt)
    set_pending(
        op_key,
        {
            "approvalId": approval_id,
            "openQuestions": pending.get("openQuestions") or [],
            "budget": _approval_total_daily_budget(saved),
            "audiences": _approval_audience_names(saved),
            "createdAt": pending.get("createdAt"),
        },
    )

    # build_autonomous_campaign only consumes `budget` (it re-ranks audiences/geo from the
    # synced analysis), so the budget override is the lever that actually changes the
    # packet. Other detected signals are acknowledged so the operator sees they registered.
    applied = []
    if "budget" in overrides:
        applied.append(f"daily budget to ${float(overrides['budget']):,.0f}/day")
    noted = []
    if "locations" in overrides:
        noted.append(f"locations ({', '.join(overrides['locations'])})")
    if "audiences" in overrides:
        noted.append(f"audiences ({', '.join(overrides['audiences'])})")
    if "successMetric" in overrides:
        noted.append(f"success metric ({overrides['successMetric']})")

    changes = "; ".join(applied) or "your latest preferences"
    answer = f"I refined your draft paused campaign — updated {changes}."
    if noted:
        answer += f" I also noted {', '.join(noted)} for the next rebuild."
    answer += " It is still PAUSED and saved for review."

    return specialist_chat_response(
        question=" ".join(applied + noted) or "refine campaign",
        answer=answer,
        sources=["opportunity_finder", "pending_context_store", "storage/meta_knowledge_base.json"],
        suggestedQuestions=[
            "Approve this paused campaign.",
            "Lower the daily budget further.",
            "Swap one of the chosen audiences.",
        ],
    )


@router.post("/api/agent/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest, *, operator_key_override: str | None = None) -> ChatResponse:
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

    # An explicit operator key (e.g. "tg:12345" from the Telegram conversational path)
    # wins so refinement state is shared across that operator's turns; otherwise derive
    # one from the web session id (or the shared web:default fallback).
    op_key = operator_key_override or operator_key(session_id=request.sessionId)

    # Type-approve: if the operator has a pending bulk-manage approval and types
    # "approve"/"reject" (or an affirmation/negation), resolve it here — execute the
    # archive/pause now (or cancel) — before any routing. Shared with Telegram.
    manage_decision = resolve_pending_manage(op_key, question)
    if manage_decision is not None:
        return specialist_chat_response(
            question,
            answer=manage_decision["answer"],
            sources=manage_decision["sources"],
            suggestedQuestions=manage_decision["suggestedQuestions"],
        )

    # Pending refinement: if the operator has an in-flight autonomous draft AND this
    # message carries a recognizable refinement signal (budget/location/etc.), rebuild
    # the SAME approval in place instead of routing as a fresh question. Keeps the
    # operator iterating on one draft instead of starting over.
    pending = get_pending(op_key)
    if pending and pending.get("approvalId") and pending.get("kind") != "manage":
        overrides = merge_refinement(pending, question, knowledge)
        if overrides:
            refined = _refine_pending_campaign(op_key, pending, overrides, knowledge)
            if refined:
                return refined

    # Factual roster questions ("what campaigns are active?") get a guaranteed,
    # data-grounded list from LIVE Meta data — never a stale snapshot, the generic
    # fallback, or orchestrator advice. Falls back to the snapshot when Meta is down.
    acct = await get_live_account(knowledge=knowledge)
    roster_sources = ["meta_live"] if acct.is_live else ["storage/meta_knowledge_base.json"]
    # A bulk-manage instruction ("archive my campaigns") must take ACTION, not be answered
    # as a roster listing — so skip the roster/config short-circuits when manage intent is
    # detected and let the orchestrator prepare the approval.
    from ..campaign_manage import detect_manage_intent

    wants_manage = detect_manage_intent(question) is not None
    if not wants_manage and (knowledge or acct.campaigns):
        roster = campaign_roster_answer(question, knowledge, campaigns=acct.campaigns, source=acct.source)
        if roster:
            return specialist_chat_response(
                question,
                answer=roster,
                sources=roster_sources,
                suggestedQuestions=[
                    "Which active campaign has the best lead rate?",
                    "Which campaign should we scale next?",
                    "What should we pause?",
                ],
            )

    # Live campaign CONFIGURATION questions ("what audience/interests/placements did
    # <campaign> use? was A/B enabled?") get a deterministic config answer from live
    # Meta data — routed EARLY, before the performance ranking path, so a config question
    # never falls through to the performance specialist. Returns None for non-config or
    # unresolved campaigns, so the performance path still wins.
    if not wants_manage and (knowledge or acct.campaigns):
        config_answer = campaign_configuration_answer(
            question,
            knowledge,
            campaigns=acct.campaigns,
            adsets=acct.adsets,
            adstudies=acct.adstudies,
            saved_audiences=acct.saved_audiences,
            source=acct.source,
        )
        if config_answer:
            config_sources = (
                ["campaign_specific_analysis", "meta_live"]
                if acct.is_live
                else ["campaign_specific_analysis", "storage/meta_knowledge_base.json"]
            )
            return specialist_chat_response(
                question,
                answer=config_answer,
                sources=config_sources,
                suggestedQuestions=[
                    "How is this campaign performing?",
                    "Which ad set should we scale?",
                    "Was an A/B test run on this campaign?",
                ],
            )

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

    orchestrated = (
        orchestrate_agent_chat(question, knowledge=knowledge, playbooks=load_playbooks(), campaigns=acct.campaigns)
        if _should_run_orchestrator(lower, routed)
        else None
    )
    if orchestrated:
        # Bulk-manage packet: record a pending pointer so "approve"/"reject" in the next
        # turn resolves THIS approval by id (type-approve, handled above on the next turn).
        if orchestrated.get("managePrepared"):
            manage_approval = orchestrated.get("generatedApprovalRequest") or {}
            if manage_approval.get("id"):
                action = "archive" if (manage_approval.get("after") or {}).get("status") == "ARCHIVED" else "pause"
                set_pending(
                    op_key,
                    {
                        "approvalId": manage_approval["id"],
                        "kind": "manage",
                        "action": action,
                        "createdAt": manage_approval.get("createdAt"),
                    },
                )
            return ChatResponse(**orchestrated)

        generated_playbook = orchestrated.get("generatedPlaybook")
        if generated_playbook:
            saved_playbook = save_playbook(generated_playbook)
            orchestrated["generatedPlaybook"] = saved_playbook
            if orchestrated.get("generatedStrategy"):
                orchestrated["generatedStrategy"]["playbookId"] = saved_playbook["id"]
            orchestrated["answer"] += "\n\nI saved this as a draft playbook in the dashboard. It is still not executed in Meta Ads."

        approval = orchestrated.get("generatedApprovalRequest")
        if orchestrated.get("autonomous") and isinstance(approval, dict) and approval.get("id"):
            # Record a pending pointer so a later turn ("$150/day", "Tashkent only")
            # refines THIS draft in place instead of starting over.
            set_pending(
                op_key,
                {
                    "approvalId": approval["id"],
                    "openQuestions": approval.get("openQuestions") or [],
                    "budget": _approval_total_daily_budget(approval),
                    "audiences": _approval_audience_names(approval),
                    "createdAt": approval.get("createdAt"),
                },
            )
            # Auto-create the PAUSED campaign immediately (no separate approval tap),
            # unless the operator opted out or the guardrail hard-failed.
            if request.autoExecute and approval.get("guardrailResult") != "fail":
                result = auto_execute_paused(approval["id"])
                if result.get("ok"):
                    orchestrated["answer"] = _append_autonomous_execution(
                        orchestrated["answer"], result.get("created", []), _ad_account_id()
                    )
                    clear_pending(op_key)
                elif result.get("blocked"):
                    orchestrated["answer"] += (
                        f"\n\nI did not auto-create it in Meta: {result['blocked']} "
                        "The PAUSED draft is saved and waiting for your approval."
                    )
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

    new_specialists = {
        "measurement": (
            answer_measurement,
            ["trackingHealth", "metrics", "storage/meta_knowledge_base.json"],
            ["Which attribution window should we use?", "Is our lead count double-counted?", "Is measurement good enough to scale?"],
        ),
        "budget_pacing": (
            answer_budget_pacing,
            ["campaigns", "metrics", "docs/AGENT_OPERATING_POLICY.md"],
            ["Are we under-pacing budget?", "Should this be CBO or ABO?", "What is a safe budget step?"],
        ),
        "landing_cro": (
            answer_landing_cro,
            ["funnel", "trackingHealth"],
            ["Where is the landing-page leak?", "Is the message-match off?", "What CRO test should we run first?"],
        ),
    }
    if routed["agentId"] in new_specialists:
        builder, sources, suggested = new_specialists[routed["agentId"]]
        answer = builder(dashboard_data)
        if knowledge:
            persona_prompt = specialist_system_prompt(routed["agentId"])
            try:
                llm_answer = await generate_specialist_answer(question, knowledge_chat_preview(knowledge), system_prompt=persona_prompt) if persona_prompt else None
            except Exception:
                llm_answer = None
            if llm_answer:
                answer = llm_answer
                sources = [*sources, "openai", routed["agentId"]]
        return specialist_chat_response(question, answer=answer, sources=sources, suggestedQuestions=suggested)

    if knowledge:
        campaign_answer = campaign_specific_answer(question, knowledge, campaigns=acct.campaigns, source=acct.source)
        if campaign_answer:
            specific_sources = ["campaign_specific_analysis", "meta_live"] if acct.is_live else ["campaign_specific_analysis", "storage/meta_knowledge_base.json"]
            return specialist_chat_response(
                question,
                answer=campaign_answer,
                sources=specific_sources,
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
                llm_answer = await generate_chat_answer(question, knowledge_chat_preview(knowledge))
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

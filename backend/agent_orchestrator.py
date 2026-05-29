from __future__ import annotations

from typing import Any

from .chat_campaign_planner import build_playbook_from_chat, can_build_playbook_from_chat
from .strategy_generator import generate_launch_strategy


AGENT_SPECS: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "name": "Orchestrator Agent",
        "purpose": "Own the chat, route work to specialists, merge answers, and create approval requests.",
        "inputs": ["user question", "knowledge base", "campaign playbooks", "approval policy"],
        "outputs": ["specialist route", "combined answer", "approval-ready action plan"],
        "tools": ["agent_registry", "strategy_generator", "approval_queue_future"],
        "canExecuteLiveChanges": False,
        "requiresApproval": True,
    },
    "audit": {
        "name": "Audit Agent",
        "purpose": "Explain what worked, what failed, and why from historical Meta, funnel, and CRM data.",
        "inputs": ["Meta insights", "settings audit", "funnel events", "CRM exports"],
        "outputs": ["lessons learned", "winners", "weak points", "data confidence notes"],
        "tools": ["knowledge_base", "dashboard_data"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "audience": {
        "name": "Audience Strategist",
        "purpose": "Recommend country/region, age, gender, interests, and purchasing-power hypotheses.",
        "inputs": ["age/gender breakdowns", "geo breakdowns", "interest performance", "business memory"],
        "outputs": ["audience ranking", "segment hypothesis", "targeting risks"],
        "tools": ["knowledge_base", "settings_audit"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "creative": {
        "name": "Creative Intelligence Agent",
        "purpose": "Rank creative performance and explain hook, visual, offer, and buyer-intent quality.",
        "inputs": ["ads", "creatives", "thumbnails", "video metadata", "future frame analysis"],
        "outputs": ["creative ranking", "replicate/avoid guidance", "creative test matrix"],
        "tools": ["creative_scores", "future_gemini_or_vision"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "placement": {
        "name": "Placement Optimizer",
        "purpose": "Compare Instagram, Facebook, Threads, Audience Network, and position-level quality.",
        "inputs": ["placement insights", "playbook placement rules", "Uzbekistan business guardrails"],
        "outputs": ["placement recommendation", "separate-test advice", "placement risks"],
        "tools": ["knowledge_base", "settings_audit"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "funnel": {
        "name": "Funnel Tracking Agent",
        "purpose": "Track landing page, Telegram, bot-step, CRM, and payment movement by visitor.",
        "inputs": ["landing events", "ChatPlace events", "Google Sheet/CRM exports", "Meta attribution"],
        "outputs": ["visit rate", "Telegram START rate", "form click rate", "qualified lead rate", "leak diagnosis"],
        "tools": ["funnel_events", "chatplace_events", "future_crm_import"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "monitoring": {
        "name": "Monitoring Agent",
        "purpose": "Check active campaigns every four hours and detect rising costs or quality drops.",
        "inputs": ["latest Meta insights", "funnel events", "playbook targets", "sales capacity"],
        "outputs": ["alerts", "top two or three recommended actions", "trend explanation"],
        "tools": ["future_automation", "dashboard_alerts"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "experiment": {
        "name": "Experiment Agent",
        "purpose": "Turn recommendations into controlled A/B tests with variables, metrics, duration, and guardrails.",
        "inputs": ["strategy", "historical lessons", "budget rules", "primary success metric"],
        "outputs": ["experiment card", "stop rule", "scale rule", "minimum evidence requirement"],
        "tools": ["strategy_generator", "approval_actions"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "meta_ai_advisor": {
        "name": "Meta AI Advisor Agent",
        "purpose": "Capture and interpret Ads Manager AI Analyze recommendations as read-only platform-side evidence.",
        "inputs": ["selected campaign/ad set/ad", "Meta AI Analyze panel text", "screenshot evidence", "Meta API metrics"],
        "outputs": ["Meta AI recommendation summary", "trust level", "business-side countercheck", "handoff to specialist agents"],
        "tools": ["browser_read_only_capture", "knowledge_base", "orchestrator_handoff"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "meta_ai_strategist": {
        "name": "Meta AI Strategist Agent",
        "purpose": "Turn captured Meta AI evidence and Meta API metrics into a Meta-side strategy for audiences, ad sets, creatives, and tests.",
        "inputs": ["Meta AI Advisor captures", "Meta API insights", "selected campaign/ad set/ad context", "historical Meta performance"],
        "outputs": ["Meta-side strategy", "best ad sets", "best interests", "top creatives", "Meta-native experiment candidates", "limitations"],
        "tools": ["meta_ai_captures", "meta_api_metrics", "specialist_handoff"],
        "canExecuteLiveChanges": False,
        "requiresApproval": False,
    },
    "execution": {
        "name": "Meta Execution Agent",
        "purpose": "After explicit approval, execute a specific Meta Ads change by API first, browser fallback second.",
        "inputs": ["approved action", "target object ID", "before/after settings", "guardrail check"],
        "outputs": ["execution log", "API/browser result", "screenshot for browser fallback"],
        "tools": ["future_meta_write_api", "future_browser_fallback"],
        "canExecuteLiveChanges": False,
        "requiresApproval": True,
    },
    "browser_operator": {
        "name": "Browser Operator",
        "purpose": "Follow an approved UI plan only when API cannot complete the approved Meta Ads action.",
        "inputs": ["specific approved UI plan", "expected object names and IDs"],
        "outputs": ["screenshots", "before/after proof", "blocked-state report"],
        "tools": ["browser_fallback"],
        "canExecuteLiveChanges": False,
        "requiresApproval": True,
    },
}


def agent_registry() -> dict[str, dict[str, Any]]:
    return {agent_id: {"id": agent_id, **spec} for agent_id, spec in AGENT_SPECS.items()}


def route_question(question: str) -> dict[str, Any]:
    lower = question.lower()
    if any(word in lower for word in ["sub-agent", "subagent", "agent role", "orchestrator", "specialist"]):
        return route("orchestrator", "Agent architecture/status question.")
    if ("meta ai" in lower or "ads manager ai" in lower) and any(
        word in lower for word in ["strategy", "strategist", "fully analyzed", "analyzed", "captures", "capture", "answers"]
    ):
        return route("meta_ai_strategist", "Captured Meta AI evidence should be converted into Meta-side strategy.")
    if any(word in lower for word in ["meta ai", "ads manager ai", "analyze button", "opportunity score", "opportunity-score"]):
        return route("meta_ai_advisor", "Meta AI Analyze request should be captured read-only and validated against business data.")
    if any(word in lower for word in ["setup", "set up", "create campaign", "launch campaign", "new campaign", "campaign plan", "vsl"]):
        return route("orchestrator", "Campaign creation/planning request should be converted into an approval-ready playbook or strategy.")
    if any(word in lower for word in ["execute", "change budget", "browser", "go to meta", "pause", "publish", "upload creative"]):
        return route("execution", "Live Meta change request requires approval and API-first execution policy.")
    if any(word in lower for word in ["creative", "video", "hook", "thumbnail", "viral", "visual"]):
        return route("creative", "Creative question needs hook, asset, and buyer-intent analysis.")
    if any(word in lower for word in ["audience", "target", "interest", "age", "gender", "country", "region", "city", "tashkent"]):
        return route("audience", "Audience question needs targeting and purchasing-power reasoning.")
    if any(word in lower for word in ["placement", "facebook", "instagram", "reels", "stories", "feed", "threads"]):
        return route("placement", "Placement question needs platform and position-level quality checks.")
    if any(word in lower for word in ["funnel", "telegram", "landing", "crm", "bitrix", "form", "pixel", "visit rate", "lead rate"]):
        return route("funnel", "Funnel question needs event tracking and attribution reasoning.")
    if any(word in lower for word in ["monitor", "alert", "every four hours", "trend", "rising", "improving", "getting expensive"]):
        return route("monitoring", "Monitoring question needs trend detection and alert rules.")
    if any(word in lower for word in ["experiment", "test", "ab test", "a/b", "scale rule", "stop rule"]):
        return route("experiment", "Experiment question needs hypothesis, variable, metric, and guardrail design.")
    return route("audit", "Default to audit agent for historical performance and lessons.")


def orchestrate_agent_chat(
    question: str,
    *,
    knowledge: dict[str, Any] | None,
    playbooks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lower = question.lower()
    routed = route_question(question)

    if any(word in lower for word in ["sub-agent", "subagent", "agent role", "orchestrator", "specialist"]):
        return response(
            routed,
            answer=describe_agent_system(),
            sources=["docs/AGENT_OPERATING_POLICY.md", "agent_orchestrator"],
            suggested=[
                "Which specialist handles campaign setup?",
                "Can the execution agent use browser fallback?",
                "Prepare the next campaign plan from saved data.",
            ],
        )

    if routed["agentId"] == "execution":
        return response(
            routed,
            answer=(
                "The Execution Agent can prepare the exact Meta Ads change, but it cannot perform live changes yet. "
                "The rule is API first, browser fallback second, and only after a specific approved action with target object, before/after value, risk, and guardrail check. "
                "I can draft that approval request here, then execute only after you approve the exact action."
            ),
            sources=["docs/AGENT_OPERATING_POLICY.md", "docs/META_EXECUTION_SAFETY.md"],
            suggested=[
                "Draft an approval request for this campaign change.",
                "What information do you need before execution?",
                "Generate a campaign plan first.",
            ],
        )

    if routed["agentId"] == "meta_ai_advisor":
        return response(
            routed,
            answer=describe_meta_ai_workflow(),
            sources=["docs/META_AI_ADVISOR_WORKFLOW.md", "agent_orchestrator", "Meta Ads Manager Analyze panel"],
            suggested=[
                "Capture Meta AI analysis for the selected campaign.",
                "Compare Meta AI recommendations with Telegram START quality.",
                "Turn accepted Meta AI advice into an experiment plan.",
            ],
        )

    if routed["agentId"] == "meta_ai_strategist":
        return response(
            routed,
            answer=describe_meta_ai_strategy_workflow(),
            sources=["docs/META_AI_ADVISOR_WORKFLOW.md", "agent_orchestrator", "storage/meta_knowledge_base.json"],
            suggested=[
                "Generate Meta-side strategy from the latest Meta AI capture.",
                "Send Meta-side creative findings to Creative Intelligence.",
                "Convert Meta AI strategy into approval-safe experiments.",
            ],
        )

    if routed["agentId"] == "orchestrator" and any(word in lower for word in ["setup", "set up", "create campaign", "launch", "campaign plan", "vsl"]):
        if can_build_playbook_from_chat(question):
            playbook = build_playbook_from_chat(question, knowledge=knowledge)
            strategy = generate_launch_strategy(playbook, knowledge)
            result = response(
                routed,
                answer=format_strategy_answer(strategy, source_label="your chat brief"),
                sources=["chat_campaign_planner", "strategy_generator", "storage/meta_knowledge_base.json", "docs/AGENT_OPERATING_POLICY.md"],
                suggested=[
                    "Save this playbook for the dashboard.",
                    "Turn this into approval requests.",
                    "What should we test in the first 48 hours?",
                ],
            )
            result["generatedPlaybook"] = playbook
            result["generatedStrategy"] = strategy
            return result

        playbook = first_playbook_with_segments(playbooks)
        if not playbook:
            return response(
                routed,
                answer=(
                    "I can build the campaign plan through chat. Tell me the segments or VSLs, daily budget, primary success metric, target locations, and any must-use interests. "
                    "If you only give a short instruction, I will use the saved Meta knowledge plus your Shahlo course rules to draft the plan and ask for approval before execution."
                ),
                sources=["agent_orchestrator", "docs/ARCHITECTURE_AND_VERSION_ROADMAP.md"],
                suggested=[
                    "Create a plan for income, business automation, and content creator VSLs.",
                    "Use $100 per segment and optimize for Telegram START.",
                    "Which inputs are required before execution?",
                ],
            )
        strategy = generate_launch_strategy(playbook, knowledge)
        return response(
            routed,
            answer=format_strategy_answer(strategy),
            sources=["strategy_generator", "storage/meta_knowledge_base.json", "docs/AGENT_OPERATING_POLICY.md"],
            suggested=[
                "Turn this into approval requests.",
                "Which segment should get the first budget?",
                "What should we test in the first 48 hours?",
            ],
        )

    return None


def first_playbook_with_segments(playbooks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for playbook in playbooks:
        if playbook.get("segments"):
            return playbook
    return None


def describe_agent_system() -> str:
    registry = agent_registry()
    lines = [
        "The sub-agent layer is now defined as an approval-safe specialist system. The Orchestrator owns chat and delegates internally; specialists analyze, but do not execute live Meta changes.",
        "",
        "Configured specialists:",
    ]
    for agent_id in [
        "audit",
        "audience",
        "creative",
        "placement",
        "funnel",
        "monitoring",
        "experiment",
        "meta_ai_advisor",
        "meta_ai_strategist",
        "execution",
        "browser_operator",
    ]:
        spec = registry[agent_id]
        permission = "approval required" if spec["requiresApproval"] else "analysis only"
        lines.append(f"- {spec['name']}: {spec['purpose']} ({permission}).")
    lines.append("")
    lines.append("Current safety level: analysis and recommendations are enabled; live execution remains blocked until approval queue and execution logs are implemented.")
    return "\n".join(lines)


def describe_meta_ai_workflow() -> str:
    return (
        "Meta AI is useful as read-only platform-side evidence, not as the final decision-maker. "
        "The Meta AI Advisor Agent should use the browser to capture the Ads Manager Analyze output for the selected campaign, ad set, or ad. "
        "It then sends that text and screenshot evidence to the Orchestrator. The Orchestrator delegates the recommendation to the right specialist: "
        "Creative Intelligence for hook/video advice, Audience Strategist for targeting advice, Placement Optimizer for placement advice, and Funnel Tracking for Telegram/landing-page quality checks. "
        "We trust Meta AI more for auction, delivery, creative efficiency, learning, and Opportunity Score signals. We trust our agents more for business-side quality: Telegram START quality, VSL intent, CRM/sales capacity, purchasing power, and course-buyer fit. "
        "No Meta AI recommendation can execute directly; it must become an experiment or approval request first."
    )


def describe_meta_ai_strategy_workflow() -> str:
    return (
        "The Meta AI Strategist turns Advisor captures into a Meta-side strategy. "
        "It analyzes which ad sets produced cheaper website registrations, which interests drove click-to-registration behavior, and which top 10 creative videos created the strongest Meta-side response. "
        "Its output is already analyzed for Meta delivery: best ad sets, best interests, top creatives, weak creatives, why Meta thinks they worked, what to test next, and confidence limits. "
        "It is not the final business strategy. The Orchestrator must still merge it with Telegram START, landing-page button clicks, CRM/sales quality, buyer purchasing power, and course positioning. "
        "The Strategist should hand off audience findings to the Audience Strategist, creative findings to Creative Intelligence, funnel concerns to Funnel Tracking, and test candidates to the Experiment Agent."
    )


def format_strategy_answer(strategy: dict[str, Any], source_label: str = "the saved playbook and knowledge base") -> str:
    segment_lines = [
        f"- {segment['name']}: ${segment['budgetUsd']:,.0f}/day, placements {', '.join(segment['recommendedPlacements'])}, interests {', '.join(segment['interestStrategy'][:3])}."
        for segment in strategy.get("segments", [])
    ]
    risk_lines = [f"- {risk}" for risk in strategy.get("risks", [])[:3]]
    action_lines = [f"- {action['title']}: {action['impact']}" for action in strategy.get("approvalActions", [])[:3]]
    return "\n".join(
        [
            f"I generated an approval-ready campaign plan from {source_label}. {strategy['summary']}",
            "",
            f"Budget: ${strategy['budget']['totalDailyBudgetUsd']:,.0f}/day total. Estimated lead load: {strategy['budget']['estimatedDailyLeadLoad']:g}/day.",
            "",
            "Segments:",
            *(segment_lines or ["- No segments found in the selected playbook."]),
            "",
            "Main risks:",
            *(risk_lines or ["- No major risks detected."]),
            "",
            "Approval queue draft:",
            *action_lines,
            "",
            "I will not execute Meta changes from this plan until you approve a specific action.",
        ]
    )


def response(
    routed: dict[str, Any],
    *,
    answer: str,
    sources: list[str],
    suggested: list[str],
) -> dict[str, Any]:
    return {
        "activeAgent": routed["agentId"],
        "routeReason": routed["reason"],
        "answer": answer,
        "sources": sources,
        "suggestedQuestions": suggested,
    }


def route(agent_id: str, reason: str) -> dict[str, Any]:
    return {
        "agentId": agent_id,
        "agentName": AGENT_SPECS[agent_id]["name"],
        "reason": reason,
    }

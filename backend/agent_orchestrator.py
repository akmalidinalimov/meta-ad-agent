from __future__ import annotations

from typing import Any

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
    if any(word in lower for word in ["setup", "set up", "create campaign", "launch campaign", "new campaign", "campaign plan"]):
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

    if routed["agentId"] == "orchestrator" and any(word in lower for word in ["setup", "set up", "create campaign", "launch", "campaign plan"]):
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
        "execution",
        "browser_operator",
    ]:
        spec = registry[agent_id]
        permission = "approval required" if spec["requiresApproval"] else "analysis only"
        lines.append(f"- {spec['name']}: {spec['purpose']} ({permission}).")
    lines.append("")
    lines.append("Current safety level: analysis and recommendations are enabled; live execution remains blocked until approval queue and execution logs are implemented.")
    return "\n".join(lines)


def format_strategy_answer(strategy: dict[str, Any]) -> str:
    segment_lines = [
        f"- {segment['name']}: ${segment['budgetUsd']:,.0f}/day, placements {', '.join(segment['recommendedPlacements'])}, interests {', '.join(segment['interestStrategy'][:3])}."
        for segment in strategy.get("segments", [])
    ]
    risk_lines = [f"- {risk}" for risk in strategy.get("risks", [])[:3]]
    action_lines = [f"- {action['title']}: {action['impact']}" for action in strategy.get("approvalActions", [])[:3]]
    return "\n".join(
        [
            f"I generated an approval-ready campaign plan from the saved playbook and knowledge base. {strategy['summary']}",
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

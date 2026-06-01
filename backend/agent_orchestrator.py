from __future__ import annotations

from typing import Any

from .agent_quality import evaluate_agent_response
from .chat_campaign_planner import build_playbook_from_chat, can_build_playbook_from_chat
from .meta_action_planner import build_action_approval, plan_meta_action
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

SPECIALIST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "audience": ("audience", "target", "interest", "age", "gender", "country", "region", "city", "tashkent"),
    "creative": ("creative", "creatives", "video", "hook", "thumbnail", "viral", "visual"),
    "placement": ("placement", "facebook", "instagram", "reels", "stories", "feed", "threads"),
    "funnel": ("funnel", "telegram", "landing", "crm", "bitrix", "form", "pixel", "visit rate", "lead rate"),
    "monitoring": ("monitor", "alert", "trend", "rising", "improving", "getting expensive"),
    "experiment": ("experiment", "test", "ab test", "a/b", "scale rule", "stop rule"),
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
    if any(word in lower for word in ["execute", "change budget", "browser", "go to meta", "pause", "publish", "upload creative"]):
        return route("execution", "Live Meta change request requires approval and API-first execution policy.")
    if len(detect_involved_agents(question)) >= 2:
        return route("orchestrator", "Multi-specialist strategy question should be delegated and merged by the orchestrator.")
    if any(word in lower for word in ["setup", "set up", "create campaign", "launch campaign", "new campaign", "campaign plan", "vsl"]):
        return route("orchestrator", "Campaign creation/planning request should be converted into an approval-ready playbook or strategy.")
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
    meta_action_plan = plan_meta_action(question)
    if should_prepare_meta_action(question, routed, meta_action_plan):
        routed = route("execution", "Natural-language Meta Ads change request requires approval before execution.")
        if meta_action_plan["needsClarification"]:
            result = response(
                routed,
                answer=meta_action_plan["clarifyingQuestion"] or "I need one more detail before preparing this Meta action.",
                sources=["meta_action_planner", "docs/AGENT_OPERATING_POLICY.md", "docs/META_EXECUTION_SAFETY.md"],
                suggested=[
                    "Include the exact campaign, ad set, or ad ID.",
                    "Include the new value I should prepare.",
                    "Ask for analysis before preparing the change.",
                ],
            )
            result["generatedMetaActionPlan"] = meta_action_plan
            return result

        approval = build_action_approval(meta_action_plan)
        result = response(
            routed,
            answer=format_meta_action_answer(meta_action_plan, approval),
            sources=["meta_action_planner", "docs/AGENT_OPERATING_POLICY.md", "docs/META_EXECUTION_SAFETY.md"],
            suggested=[
                "Approve this action.",
                "Reject this action.",
                "Ask the agent to revise the requested value.",
            ],
        )
        result["generatedMetaActionPlan"] = meta_action_plan
        result["generatedApprovalRequest"] = approval
        return result

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

    if routed["agentId"] == "orchestrator" and len(detect_involved_agents(question)) >= 2:
        involved = detect_involved_agents(question)
        return response(
            routed,
            answer=format_multi_specialist_answer(involved),
            sources=["agent_orchestrator", "storage/meta_knowledge_base.json", "docs/AGENT_OPERATING_POLICY.md"],
            suggested=[
                "Generate a campaign plan from the saved playbook.",
                "Ask the Creative Agent for the top replicate and avoid list.",
                "Ask the Audience Agent for target hypotheses with confidence limits.",
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


def format_meta_action_answer(plan: dict[str, Any], approval: dict[str, Any]) -> str:
    target = plan.get("target", {})
    after = plan.get("after", {})
    return "\n".join(
        [
            "I prepared this as an approval-gated Meta action.",
            "",
            f"Action: {approval.get('actionType', 'meta_action_request')}",
            f"Target: {target.get('level', 'object')} {target.get('id', 'unknown')}",
            f"New value: {after}",
            f"Risk: {approval.get('risk', 'medium')}",
            "",
            "I will not execute it until you approve the exact action. API execution is preferred; browser fallback is only for approved actions that cannot be completed through the API.",
        ]
    )


def format_multi_specialist_answer(involved: list[str]) -> str:
    agent_names = [AGENT_SPECS[agent]["name"] for agent in involved if agent in AGENT_SPECS]
    return "\n".join(
        [
            "I will handle this through the Orchestrator because the question needs several specialists, not a single-agent answer.",
            "",
            f"Agents involved: {', '.join(agent_names)}.",
            "",
            "Decision rule: use Meta-side data for delivery signals, then verify with landing-page, Telegram START, CRM, and sales-capacity quality before turning any recommendation into an approval request.",
            "",
            "I will not execute or publish changes from this analysis. The output should become a campaign plan, experiment card, or approval request after the evidence is checked.",
        ]
    )


def should_prepare_meta_action(question: str, routed: dict[str, Any], plan: dict[str, Any]) -> bool:
    if plan["intent"] == "unknown":
        return False
    lower = question.lower()
    if "meta ai" in lower or "ads manager ai" in lower:
        return False
    if routed["agentId"] == "orchestrator" and any(
        phrase in lower for phrase in ["create a campaign", "create campaign", "set up", "setup", "launch campaign", "campaign plan"]
    ):
        return False
    if plan["intent"] in {"rename", "pause", "enable"}:
        return True
    if plan["intent"] == "change_budget":
        return bool(plan.get("after")) and ("budget" in lower or "$" in lower)
    if routed["agentId"] == "execution" and any(phrase in lower for phrase in ["change placement", "change targeting", "update placement", "update targeting"]):
        return True
    return False


def response(
    routed: dict[str, Any],
    *,
    answer: str,
    sources: list[str],
    suggested: list[str],
) -> dict[str, Any]:
    payload = {
        "activeAgent": routed["agentId"],
        "routeReason": routed["reason"],
        "answer": answer,
        "sources": sources,
        "suggestedQuestions": suggested,
        "agentHandoffs": build_agent_handoffs(routed["agentId"]),
    }
    payload["agentDecision"] = build_agent_decision(routed, payload)
    payload["quality"] = evaluate_agent_response(payload)
    return payload


def build_agent_decision(routed: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    handoff_agents = [handoff["toAgent"] for handoff in payload.get("agentHandoffs", []) if handoff.get("toAgent")]
    involved = list(dict.fromkeys([*handoff_agents] or [routed["agentId"]]))
    high_confidence_handoffs = sum(1 for handoff in payload.get("agentHandoffs", []) if handoff.get("confidence") in {"high", "medium"})
    confidence_score = 95 if payload.get("sources") and payload.get("suggestedQuestions") else 75
    if routed["agentId"] == "orchestrator" and high_confidence_handoffs >= 3:
        confidence_score = 100
    if routed["agentId"] == "execution":
        confidence_score = 95 if payload.get("sources") else 70
    return {
        "primaryAgent": routed["agentId"],
        "involvedAgents": involved,
        "approvalRequired": routed["agentId"] in {"orchestrator", "execution", "browser_operator"},
        "confidenceScore": confidence_score,
        "reason": routed["reason"],
        "evidenceNeeds": build_evidence_needs(involved),
    }


def build_evidence_needs(involved_agents: list[str]) -> list[str]:
    needs: list[str] = []
    if "audience" in involved_agents:
        needs.append("Audience breakdowns with purchasing-power and location context.")
    if "creative" in involved_agents:
        needs.append("Creative ranking with hook, visual, offer, and buyer-intent notes.")
    if "placement" in involved_agents:
        needs.append("Placement-level CPC, CPL, lead rate, and downstream quality.")
    if "funnel" in involved_agents:
        needs.append("Landing click, Telegram START, form click, and CRM attribution events.")
    if "experiment" in involved_agents:
        needs.append("One-variable test plan with stop and scale rules.")
    return needs


def detect_involved_agents(question: str) -> list[str]:
    lower = question.lower()
    return [
        agent
        for agent, keywords in SPECIALIST_KEYWORDS.items()
        if any(keyword in lower for keyword in keywords)
    ]


def build_agent_handoffs(agent_id: str) -> list[dict[str, Any]]:
    handoff_map: dict[str, list[dict[str, Any]]] = {
        "orchestrator": [
            handoff("orchestrator", "audience", "Validate target segments, locations, interests, age, gender, and purchasing power.", ["campaign playbook", "Meta audience breakdowns", "CRM quality signals"], "Audience ranking and targeting risks", "high"),
            handoff("orchestrator", "creative", "Validate creative angles, hooks, proof, and buyer intent for each segment.", ["campaign playbook", "creative scores", "historical creative lessons"], "Creative replicate/avoid matrix", "high"),
            handoff("orchestrator", "placement", "Check whether Instagram-only or placement-specific tests are justified.", ["placement insights", "playbook placement rules"], "Placement recommendation and weak-placement watchlist", "medium"),
            handoff("orchestrator", "funnel", "Confirm landing, Telegram, and CRM attribution readiness before launch.", ["landing tracker config", "Telegram bot mapping", "Bitrix form fields"], "Funnel readiness and missing tracking fields", "high"),
            handoff("orchestrator", "experiment", "Turn the strategy into approval-safe tests with stop and scale rules.", ["strategy", "budget guardrails", "primary success metric"], "Experiment cards and guardrail rules", "high"),
        ],
        "meta_ai_advisor": [
            handoff("meta_ai_advisor", "meta_ai_strategist", "Convert captured Ads Manager AI advice into Meta-side strategy.", ["Meta AI text", "selected object context", "screenshot evidence"], "Meta-side audience, creative, and test recommendations", "medium"),
            handoff("meta_ai_advisor", "funnel", "Countercheck Meta-side advice against landing, Telegram, and CRM quality.", ["Meta AI recommendation", "funnel summary", "CRM lead attribution"], "Business-quality validation and caveats", "medium"),
        ],
        "meta_ai_strategist": [
            handoff("meta_ai_strategist", "audience", "Validate Meta AI audience claims against purchasing power and downstream quality.", ["Meta AI strategy", "audience rankings", "CRM/funnel quality"], "Accepted/rejected audience hypotheses", "medium"),
            handoff("meta_ai_strategist", "creative", "Validate top creative claims against buyer intent and course fit.", ["Meta AI creative findings", "creative scores", "video/hook notes"], "Creative replicate/avoid guidance", "medium"),
            handoff("meta_ai_strategist", "funnel", "Check whether Meta-side winners produce Telegram START and CRM form quality.", ["Meta AI strategy", "funnel events", "CRM imported leads"], "Funnel-quality countercheck", "medium"),
            handoff("meta_ai_strategist", "experiment", "Convert accepted Meta AI findings into controlled tests.", ["accepted Meta AI findings", "budget guardrails"], "Experiment cards requiring approval", "medium"),
        ],
        "execution": [
            handoff("execution", "browser_operator", "Use only if an already-approved Meta action cannot be completed through the API.", ["approved action", "target object ID", "before/after settings"], "Browser fallback result or blocked-state report", "blocked_until_approval"),
        ],
        "monitoring": [
            handoff("monitoring", "experiment", "Turn alerts into controlled tests instead of immediate live changes.", ["alert", "metric deltas", "guardrails"], "Two or three approval-safe next actions", "medium"),
        ],
        "funnel": [
            handoff("funnel", "audit", "Feed funnel leaks and attribution health into historical performance lessons.", ["funnel summary", "CRM attribution", "campaign context"], "Funnel leak diagnosis and data-confidence notes", "medium"),
        ],
        "creative": [
            handoff("creative", "experiment", "Convert creative winners and risks into testable creative variations.", ["creative ranking", "hook analysis", "buyer-intent notes"], "Creative experiment matrix", "medium"),
        ],
        "audience": [
            handoff("audience", "experiment", "Convert audience hypotheses into controlled targeting tests.", ["audience ranking", "purchasing-power notes", "geo/interest candidates"], "Audience experiment matrix", "medium"),
        ],
        "placement": [
            handoff("placement", "experiment", "Convert placement findings into safe placement tests.", ["placement ranking", "platform quality notes"], "Placement experiment matrix", "medium"),
        ],
    }
    return handoff_map.get(agent_id, [])


def handoff(
    from_agent: str,
    to_agent: str,
    reason: str,
    inputs_needed: list[str],
    expected_output: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "fromAgent": from_agent,
        "toAgent": to_agent,
        "reason": reason,
        "inputsNeeded": inputs_needed,
        "expectedOutput": expected_output,
        "confidence": confidence,
    }


def route(agent_id: str, reason: str) -> dict[str, Any]:
    return {
        "agentId": agent_id,
        "agentName": AGENT_SPECS[agent_id]["name"],
        "reason": reason,
    }

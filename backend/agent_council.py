from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .agent_orchestrator import AGENT_SPECS
from .chat_campaign_planner import build_playbook_from_chat, can_build_playbook_from_chat
from .specialist_findings import collect_findings
from .strategy_generator import generate_launch_strategy


COUNCIL_AGENT_IDS = [
    "orchestrator",
    "audit",
    "meta_ai_strategist",
    "audience",
    "creative",
    "placement",
    "funnel",
    "experiment",
    "monitoring",
    "execution",
]


def should_run_strategy_council(message: str) -> bool:
    lower = message.lower()
    council_markers = [
        "strategy council",
        "agent council",
        "agents talk",
        "talk to each other",
        "communicate proactively",
        "challenge each other",
        "critique each other",
        "squeeze the best",
        "best possible campaign",
        "run council",
    ]
    if any(marker in lower for marker in council_markers):
        return True
    return (
        "create" in lower
        and "campaign" in lower
        and any(word in lower for word in ["audience", "creative", "placement", "funnel", "experiment"])
    )


def run_strategy_council(
    question: str,
    *,
    knowledge: dict[str, Any] | None,
    playbooks: list[dict[str, Any]],
) -> dict[str, Any]:
    playbook = select_council_playbook(question, playbooks)
    strategy = generate_launch_strategy(playbook, knowledge)
    analysis = (knowledge or {}).get("analysis", {})
    findings = collect_findings(knowledge)
    evidence = extract_council_evidence(analysis, findings)

    agents = [build_council_agent(agent_id) for agent_id in COUNCIL_AGENT_IDS]
    rounds = [
        build_initial_round(question, evidence),
        build_challenge_round(evidence, findings),
        build_synthesis_round(strategy, evidence),
    ]
    events = [event for round_item in rounds for event in round_item["events"]]
    scores = score_council_agents(events, strategy, findings)
    average_score = round(sum(item["scoreOutOf10"] for item in scores) / len(scores), 2)
    final_plan = build_final_plan(strategy, evidence)
    session = {
        "id": f"council_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "ready_for_review",
        "question": question,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "rounds": rounds,
        "events": events,
        "scores": scores,
        "averageScoreOutOf10": average_score,
        "quality": {
            "score": int(round(average_score * 10)),
            "status": "usable" if average_score >= 7.0 else "needs_refinement",
            "issues": [] if average_score >= 7.0 else ["Council evidence is thin; resync Meta data or narrow the brief for stronger conviction."],
        },
        "finalPlan": final_plan,
        "generatedPlaybook": playbook,
        "generatedStrategy": strategy,
        "approvalRequired": True,
        "executionSafety": {
            "publishBlocked": True,
            "liveSpendAllowed": False,
            "rule": "The council may create an approval packet or paused campaign draft, but it cannot publish or activate spend without explicit approval.",
        },
    }
    return session


def select_council_playbook(question: str, playbooks: list[dict[str, Any]]) -> dict[str, Any]:
    if can_build_playbook_from_chat(question):
        return build_playbook_from_chat(question, knowledge=None)
    for playbook in playbooks:
        if playbook.get("segments"):
            return playbook
    return build_playbook_from_chat(
        "Create a campaign with 3 VSLs: earning money income, business automation agents, content creators video editors. "
        "Use $100 each and optimize for Telegram START.",
        knowledge=None,
    )


def build_council_agent(agent_id: str) -> dict[str, Any]:
    spec = AGENT_SPECS[agent_id]
    return {
        "id": agent_id,
        "name": spec["name"],
        "role": spec["purpose"],
        "state": "ready",
        "requiresApproval": spec["requiresApproval"],
    }


def extract_council_evidence(analysis: dict[str, Any], findings: dict[str, Any] | None = None) -> dict[str, Any]:
    findings = findings or {}
    top_ads = analysis.get("topAds") or []
    audience = analysis.get("audience") or {}
    placements = analysis.get("placements") or []
    summary = analysis.get("summary") or {}
    # Prefer the real specialist findings (ad-set / creative / placement winners)
    # over raw analysis order when they are available.
    creative_best = _finding_label(findings.get("creative", {}).get("best"))
    audience_best = _finding_label(findings.get("audience", {}).get("best"))
    placement_best = _finding_label(findings.get("placement", {}).get("best"))
    return {
        "topCreative": creative_best or first_label(top_ads, "VID - 08"),
        "topAudience": audience_best or first_label(audience.get("interests") or [], "Artificial intelligence"),
        "topPlacement": placement_best or first_label(placements, "instagram / reels"),
        "leadCount": int(float(summary.get("leads") or 0)),
        "purchaseCount": int(float(summary.get("purchases") or 0)),
        "topAds": [item.get("label") for item in top_ads[:3] if item.get("label")],
        "topInterests": [item.get("label") for item in (audience.get("interests") or [])[:3] if item.get("label")],
        "topPlacements": [item.get("label") for item in placements[:3] if item.get("label")],
        "lessons": analysis.get("lessons") or [],
    }


def _finding_label(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    keys = item.get("keys", {}) or {}
    return keys.get("ad_name") or item.get("label") or keys.get("ad_id")


def first_label(rows: list[dict[str, Any]], fallback: str) -> str:
    if rows and rows[0].get("label"):
        return str(rows[0]["label"])
    return fallback


def build_initial_round(question: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "round_1_initial",
        "title": "Round 1 - Specialist recommendations",
        "purpose": "Each agent states its best recommendation and the evidence it needs.",
        "events": [
            council_event("orchestrator", "audit", "Audit the historical winners and failures before planning the new campaign.", "Use the 180-day knowledge base, but treat purchases as missing until CRM data is connected."),
            council_event("audit", "audience", "Which audience is cheap but potentially low quality, and which audience may pay?", f"Lead volume is {evidence['leadCount']:,}; purchases in Meta are {evidence['purchaseCount']:,}, so buyer quality must be validated downstream."),
            council_event("audit", "creative", "Which top creatives should be reused without repeating low-quality viral mistakes?", f"Start from {', '.join(evidence['topAds'] or [evidence['topCreative']])}."),
            council_event("audit", "placement", "Which placements should be isolated so cheap traffic does not distort quality?", f"Primary placement evidence: {', '.join(evidence['topPlacements'] or [evidence['topPlacement']])}."),
            council_event("audit", "funnel", "What tracking must be present before scale decisions?", "Require landing visit, Telegram START, form click, CRM stage, and purchase quality."),
        ],
    }


def build_challenge_round(evidence: dict[str, Any], findings: dict[str, Any] | None = None) -> dict[str, Any]:
    findings = findings or {}
    if not findings:
        # No synced knowledge: fall back to the guardrail-only challenge script.
        events = [
            council_event("creative", "audience", "If we reuse the highest-volume creative, will it attract buyers or only low-intent registrations?", "Do not scale curiosity or housewife-style traffic unless Telegram START and CRM quality hold."),
            council_event("audience", "creative", "Can the creative qualify employees, business owners, SMM agencies, and AI-income seekers in the first three seconds?", "Use proof, income path, and practical course value earlier than entertainment."),
            council_event("placement", "experiment", "Should Instagram Reels, Stories, and Feed be one ad set or separated?", "Separate Facebook tests; keep Instagram surfaces primary until downstream quality says otherwise."),
            council_event("funnel", "experiment", "What is the stop rule if leads are cheap but Telegram START is weak?", "Stop or isolate when landing lead rate is strong but Telegram START or CRM quality falls below benchmark."),
            council_event("meta_ai_strategist", "orchestrator", "Which Meta-side signals can be trusted and which must be challenged?", "Trust auction/creative-efficiency signals; challenge anything that ignores sales capacity and buyer quality."),
            council_event("monitoring", "execution", "What can be changed automatically after the campaign is created?", "Nothing live. Prepare paused drafts or approval requests only; monitor every four hours after launch."),
        ]
    else:
        # Real agent-to-agent challenge: each challenge is answered with the addressed
        # agent's own computed finding (its headline + top risk), so agents respond with
        # real evidence rather than scripted lines.
        events = [
            council_event(
                "creative", "audience",
                f"If we lead with {evidence['topCreative']}, does the audience evidence support buyers or only cheap registrations?",
                _finding_reply(findings.get("audience", {})),
            ),
            council_event(
                "audience", "creative",
                f"Can {evidence['topCreative']} qualify higher-purchasing-power segments in the first three seconds?",
                _finding_reply(findings.get("creative", {})),
            ),
            council_event(
                "placement", "experiment",
                f"Should we scale {evidence['topPlacement']} and isolate weaker placements?",
                _finding_reply(findings.get("placement", {})),
            ),
            council_event(
                "funnel", "experiment",
                "What is the stop rule if leads are cheap but downstream quality is weak?",
                _finding_reply(findings.get("funnel", {})),
            ),
            council_event(
                "audit", "orchestrator",
                "What does the historical account evidence say before we scale?",
                _finding_reply(findings.get("audit", {})),
            ),
            council_event("monitoring", "execution", "What can be changed automatically after the campaign is created?", "Nothing live. Prepare paused drafts or approval requests only; monitor every four hours after launch."),
        ]
    return {
        "id": "round_2_challenge",
        "title": "Round 2 - Cross-agent challenge",
        "purpose": "Agents challenge weak assumptions and answer with their own real findings.",
        "events": events,
    }


def _finding_reply(finding: dict[str, Any]) -> str:
    headline = finding.get("headline", "Not enough evidence yet.")
    risks = finding.get("risks", [])
    return f"{headline} {risks[0]}" if risks else headline


def build_synthesis_round(strategy: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    segment_names = ", ".join(segment["name"] for segment in strategy.get("segments", []))
    return {
        "id": "round_3_synthesis",
        "title": "Round 3 - Final synthesis",
        "purpose": "The Orchestrator resolves conflicts and creates one approval-safe plan.",
        "events": [
            council_event("orchestrator", "audience", "Final audience decision", f"Use configurable segments ({segment_names}) and validate interests against Telegram/CRM quality."),
            council_event("orchestrator", "creative", "Final creative decision", f"Use top historical creatives first, led by {evidence['topCreative']}, but rewrite messaging toward buyer intent."),
            council_event("orchestrator", "placement", "Final placement decision", f"Use {evidence['topPlacement']} as the primary hypothesis and keep weak placements isolated."),
            council_event("orchestrator", "experiment", "Final test decision", "Run one-variable tests with stop and scale rules; no broad budget increase from cheap CPL alone."),
            council_event("orchestrator", "execution", "Final execution decision", "Create paused campaign/ad sets/ads only after approval; publish remains blocked."),
        ],
    }


def council_event(from_agent: str, to_agent: str, question: str, answer: str) -> dict[str, Any]:
    return {
        "id": f"{from_agent}_to_{to_agent}_{abs(hash((from_agent, to_agent, question))) % 100000}",
        "fromAgent": from_agent,
        "toAgent": to_agent,
        "question": question,
        "answer": answer,
        "state": "complete",
    }


def score_council_agents(events: list[dict[str, Any]], strategy: dict[str, Any], findings: dict[str, Any]) -> list[dict[str, Any]]:
    """Score each council agent by the REAL strength of its evidence.

    Specialist agents score on their finding's evidence score (which varies with
    sample size and purchase proof); coordination agents score on plan
    completeness and the average specialist evidence — so a thin knowledge base
    yields honestly lower scores instead of a constant ~9.5.
    """
    specialist_scores = {agent_id: float(finding.get("evidenceScore", 5.0)) for agent_id, finding in findings.items()}
    avg_specialist = round(sum(specialist_scores.values()) / len(specialist_scores), 1) if specialist_scores else 5.0
    coordination_base = 6.0 + (0.8 if strategy.get("approvalActions") else 0.0) + (0.6 if strategy.get("segments") else 0.0)

    scores = []
    for agent_id in COUNCIL_AGENT_IDS:
        if agent_id in specialist_scores:
            score = specialist_scores[agent_id]
            reason = findings[agent_id].get("headline", "Contributed real evidence.")
        elif agent_id == "orchestrator":
            score = round((avg_specialist + coordination_base) / 2, 1)
            reason = "Synthesized the specialist findings into one approval-safe plan."
        else:
            score = round(coordination_base, 1)
            reason = "Provided coordination, Meta-side reads, and approval-safe guardrails."
        scores.append({
            "agentId": agent_id,
            "scoreOutOf10": round(min(max(score, 0.0), 10.0), 1),
            "reason": reason,
        })
    return scores


def build_final_plan(strategy: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": strategy.get("summary", "Create an approval-safe Meta campaign using historical VSL evidence."),
        "campaignNamingRule": "Use the last-three-month VSL pattern: DA - SHAHLOAI - VSL TEST - DD.MM.YYYY - REVIEW ONLY or CODEX PAUSED.",
        "audienceDecision": {
            "primary": evidence.get("topAudience"),
            "segments": [
                {
                    "name": segment["name"],
                        "budgetUsd": segment["budgetUsd"],
                        "interests": segment["interestStrategy"][:5],
                        "locations": segment["geoStrategy"].get("locations", []),
                        "confidence": segment.get("confidence", "medium_until_telegram_crm_quality_confirms"),
                }
                for segment in strategy.get("segments", [])
            ],
        },
        "creativeDecision": {
            "topCreative": evidence.get("topCreative"),
            "topCreativePool": evidence.get("topAds", []),
            "rule": "Use high-performing VSL creatives, but qualify buyer intent earlier with proof, income path, and course value.",
        },
        "placementDecision": {
            "primary": evidence.get("topPlacement"),
            "rule": "Keep Instagram placements primary and isolate Facebook or other cheap placements until Telegram/CRM quality confirms value.",
        },
        "funnelDecision": {
            "requiredEvents": ["landing_page_view", "landing_button_click", "telegram_start", "crm_form_submit", "crm_stage", "purchase"],
            "rule": "Do not scale from Meta leads alone; require Telegram START and CRM quality before budget increases.",
        },
        "experimentDecision": strategy.get("testMatrix", [])[:5],
        "monitoringDecision": {
            "cadenceHours": 4,
            "watchMetrics": ["CPL", "landing visit rate", "Telegram START rate", "CRM quality", "creative fatigue"],
            "rule": "Recommend changes every four hours, but require approval before execution.",
        },
        "executionDecision": {
            "canCreatePausedDraft": True,
            "canPublish": False,
            "approvalRequired": True,
        },
    }

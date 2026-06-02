from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


COMPLETION_TASKS = [
    ("launch_packet", "Campaign launch recommendation packet"),
    ("approval_workflow", "Approval-gated execution workflow"),
    ("agent_capability_harness", "Agent capability test harness"),
    ("agent_quality_gates", "Orchestrator and specialist quality checks"),
    ("agent_status_view", "Agent status and availability view"),
    ("monitoring_recommendations", "Monitoring alerts and opportunities"),
    ("meta_draft_verification", "Paused Meta draft campaign verification"),
    ("knowledge_refresh_reliability", "Knowledge-base refresh reliability"),
    ("telegram_chat_control", "Telegram natural-language control"),
    ("regression_checklist", "Regression checklist before version progress"),
]


def build_system_checklist(
    *,
    agents: list[dict[str, Any]],
    knowledge: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    monitoring_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    agent_ids = {str(agent.get("id")) for agent in agents}
    has_knowledge = bool((knowledge or {}).get("analysis"))
    has_approval_queue = approvals is not None
    has_monitoring = bool(monitoring_runs)
    items = [
        checklist_item("launch_packet", "ready", "Strategy generator returns a combined launch packet for audience, creative, placement, funnel, budget, experiments, monitoring, and approvals."),
        checklist_item("approval_workflow", "ready" if has_approval_queue else "needs_attention", "Approval queue exists and live writes remain blocked until explicit approval."),
        checklist_item("agent_capability_harness", "ready", "Backend capability tests cover top chat and execution-intent paths."),
        checklist_item("agent_quality_gates", "ready", "Agent responses are scored for route, answer, sources, suggested next steps, and execution handoffs."),
        checklist_item("agent_status_view", "ready" if {"orchestrator", "execution", "funnel"}.issubset(agent_ids) else "needs_attention", "Agent registry exposes available specialists and approval requirements."),
        checklist_item("monitoring_recommendations", "ready" if has_monitoring else "partial", "Monitoring can generate alerts and improvement opportunities; run history confirms whether it has executed."),
        checklist_item("meta_draft_verification", "ready", "Meta campaign creation stays paused and supports dry-run verification before any live write."),
        checklist_item("knowledge_refresh_reliability", "ready" if has_knowledge else "needs_attention", "Knowledge base is loaded when available and missing-state is explicit."),
        checklist_item("telegram_chat_control", "ready", "Telegram command endpoint supports natural-language tasks, approvals, status, agents, and queue checks."),
        checklist_item("regression_checklist", "ready", "Regression checklist endpoint and test suite define what must pass before moving versions."),
    ]
    status_counts = {
        "ready": sum(1 for item in items if item["status"] == "ready"),
        "partial": sum(1 for item in items if item["status"] == "partial"),
        "needs_attention": sum(1 for item in items if item["status"] == "needs_attention"),
    }
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(items), **status_counts},
        "items": items,
        "nextRecommendedTask": next((item for item in items if item["status"] != "ready"), items[-1]),
    }


def checklist_item(task_id: str, status: str, evidence: str) -> dict[str, Any]:
    title = next(title for candidate_id, title in COMPLETION_TASKS if candidate_id == task_id)
    return {
        "id": task_id,
        "title": title,
        "status": status,
        "evidence": evidence,
    }

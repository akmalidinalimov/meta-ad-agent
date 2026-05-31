from __future__ import annotations

from typing import Any


def evaluate_agent_response(response: dict[str, Any]) -> dict[str, Any]:
    issues = []
    if not str(response.get("activeAgent") or "").strip():
        issues.append("missing_active_agent")
    if not str(response.get("routeReason") or "").strip():
        issues.append("missing_route_reason")
    if not str(response.get("answer") or "").strip():
        issues.append("missing_answer")
    if not response.get("sources"):
        issues.append("missing_sources")
    if not response.get("suggestedQuestions"):
        issues.append("missing_next_steps")
    if "generatedApprovalRequest" in response and not response.get("agentHandoffs"):
        issues.append("missing_execution_handoff")

    score = max(0, 100 - (len(issues) * 20))
    if "missing_answer" in issues:
        status = "blocked"
    elif score < 95:
        status = "needs_refinement"
    else:
        status = "usable"

    return {
        "score": score,
        "status": status,
        "issues": issues,
    }

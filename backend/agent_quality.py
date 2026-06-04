from __future__ import annotations

import re
from typing import Any


_NUMBER = re.compile(r"\d")
_SCALE_INTENT = ("scale", "increase budget", "raise budget", "double down", "pour more")
_BUYER_CAVEAT = (
    "lead quality",
    "lead/click",
    "not buyer",
    "no purchase",
    "no attributed purchase",
    "proxy",
    "telegram start",
    "before scaling",
)


def evaluate_agent_response(response: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Two-axis evaluation.

    `completeness` (the original structural gate, kept as score/status/issues for
    backward compatibility): are the envelope fields present? `substance`: does the
    answer actually cite a number and avoid recommending a scale-up on an account with
    zero attributed purchases without the buyer-quality caveat? The structural gate
    cannot measure thinness, so a confidently-wrong answer used to score 100; the
    substance axis flags that separately rather than letting it pass silently.
    """
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
        "substance": evaluate_substance(response, context),
    }


def evaluate_substance(response: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    lower = answer.lower()
    notes: list[str] = []

    cites_number = bool(_NUMBER.search(answer))
    if not cites_number and answer.strip():
        notes.append("answer cites no specific number/metric")

    # When the account has no attributed purchases, a scale recommendation must carry
    # the buyer-quality caveat — otherwise it green-lights spending on cheap leads.
    no_purchase = False
    if context:
        summary = context.get("summary") or context
        try:
            no_purchase = float(summary.get("purchases") or 0) == 0 and float(summary.get("leads") or 0) > 0
        except (TypeError, ValueError, AttributeError):
            no_purchase = False
    recommends_scale = any(phrase in lower for phrase in _SCALE_INTENT)
    has_caveat = any(phrase in lower for phrase in _BUYER_CAVEAT)
    unsafe_scale = bool(no_purchase and recommends_scale and not has_caveat)
    if unsafe_scale:
        notes.append("recommends scaling with zero attributed purchases and no buyer-quality caveat")

    substance_score = 100
    if not cites_number and answer.strip():
        substance_score -= 30
    if unsafe_scale:
        substance_score -= 40

    return {
        "citesNumber": cites_number,
        "recommendsScaleWithoutBuyerProof": unsafe_scale,
        "substanceScore": max(0, substance_score),
        "notes": notes,
    }

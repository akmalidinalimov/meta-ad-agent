from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def plan_meta_action(message: str) -> dict[str, Any]:
    lower = message.lower()
    intent = detect_intent(lower)
    target_level = detect_target_level(lower)
    target_id = detect_target_id(message)
    after = detect_after(intent, message)
    # A bare 8+ digit number (no explicit "campaign/ad set/ad <id>") could be a date,
    # phone, or budget — too risky to execute against. Require an explicit target.
    ambiguous_target = bool(target_id) and not is_explicit_target(message)
    needs_clarification = not target_id or not intent or not after or ambiguous_target
    return {
        "intent": intent or "unknown",
        "target": {
            "level": target_level,
            "id": target_id,
            "name": target_id or "unknown",
        },
        "before": {},
        "after": after,
        "reason": f"User requested: {message}",
        "risk": risk_for_intent(intent),
        "expectedImpact": expected_impact(intent),
        "guardrailResult": "warn" if needs_clarification else "pass",
        "guardrailChecks": guardrail_checks(intent, target_id, after),
        "executionMethod": "api",
        "requiresApproval": True,
        "needsClarification": needs_clarification,
        "clarifyingQuestion": clarifying_question(intent, target_level, target_id, after, ambiguous_target),
    }


def build_action_approval(plan: dict[str, Any]) -> dict[str, Any]:
    action_type = {
        "rename": "rename_meta_object",
        "change_budget": "change_meta_budget",
        "pause": "pause_meta_object",
        "enable": "enable_meta_object",
        "change_placement": "change_meta_placement",
        "change_targeting": "change_meta_targeting",
    }.get(plan.get("intent"), "meta_action_request")
    blocked = plan.get("needsClarification") or plan.get("guardrailResult") == "fail"
    return {
        "id": f"approval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "actionType": action_type,
        "target": plan.get("target", {}),
        "before": plan.get("before", {}),
        "after": plan.get("after", {}),
        "reason": plan.get("reason", "Natural language Meta action request."),
        "risk": plan.get("risk", "medium"),
        "expectedImpact": plan.get("expectedImpact", "Apply the requested Meta setting after approval."),
        "guardrailResult": "fail" if blocked else plan.get("guardrailResult", "warn"),
        "guardrailChecks": plan.get("guardrailChecks", []),
        "executionMethod": plan.get("executionMethod", "api"),
        "requiresApproval": True,
        "status": "blocked" if blocked else "needs_review",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def detect_intent(lower: str) -> str | None:
    if any(word in lower for word in ["rename", "change name", "call it"]):
        return "rename"
    if "budget" in lower or re.search(r"\$\s*\d+", lower):
        return "change_budget"
    if any(word in lower for word in ["pause", "turn off", "stop"]):
        return "pause"
    if any(word in lower for word in ["enable", "turn on", "activate"]):
        return "enable"
    if any(word in lower for word in ["placement", "reels", "stories", "feed", "facebook", "instagram"]):
        return "change_placement"
    if any(word in lower for word in ["targeting", "interest", "audience", "age", "gender", "location"]):
        return "change_targeting"
    return None


def detect_target_level(lower: str) -> str:
    if "ad set" in lower or "adset" in lower:
        return "adset"
    if " ad " in f" {lower} ":
        return "ad"
    return "campaign" if "campaign" in lower else "unknown"


_EXPLICIT_TARGET_RE = re.compile(r"\b(?:campaign|adset|ad set|ad)\s+([0-9]{4,})\b", flags=re.IGNORECASE)


def detect_target_id(message: str) -> str | None:
    explicit = _EXPLICIT_TARGET_RE.search(message)
    if explicit:
        return explicit.group(1)
    any_id = re.search(r"\b([0-9]{8,})\b", message)
    return any_id.group(1) if any_id else None


def is_explicit_target(message: str) -> bool:
    """True when the message names the object level + id (e.g. 'campaign 12345678'),
    not just a bare number that happens to be 8+ digits."""
    return bool(_EXPLICIT_TARGET_RE.search(message))


def detect_after(intent: str | None, message: str) -> dict[str, Any]:
    if intent == "rename":
        match = re.search(r"\b(?:to|as|called)\s+(.+)$", message, flags=re.IGNORECASE)
        return {"name": clean_value(match.group(1))} if match else {}
    if intent == "change_budget":
        match = re.search(r"\$\s*(\d+(?:\.\d+)?)", message)
        if not match:
            match = re.search(r"\b(?:budget|spend)\s+(?:to|at|as)?\s*(\d+(?:\.\d+)?)", message, flags=re.IGNORECASE)
        return {"daily_budget_usd": float(match.group(1))} if match else {}
    if intent == "pause":
        return {"status": "PAUSED"}
    if intent == "enable":
        return {"status": "ACTIVE"}
    if intent == "change_placement":
        return {"placement_instruction": message}
    if intent == "change_targeting":
        return {"targeting_instruction": message}
    return {}


def clean_value(value: str) -> str:
    return value.strip().strip("\"'")


def risk_for_intent(intent: str | None) -> str:
    if intent in {"change_budget", "enable", "change_targeting"}:
        return "high" if intent == "enable" else "medium"
    return "low" if intent == "rename" else "medium"


def expected_impact(intent: str | None) -> str:
    return {
        "rename": "Improve naming clarity without changing delivery.",
        "change_budget": "Change spend pacing after approval.",
        "pause": "Stop delivery for the selected object after approval.",
        "enable": "Resume delivery for the selected object after approval.",
        "change_placement": "Change delivery surfaces after approval.",
        "change_targeting": "Change audience delivery after approval.",
    }.get(intent, "Prepare a Meta action for human review.")


def guardrail_checks(intent: str | None, target_id: str | None, after: dict[str, Any]) -> list[dict[str, str]]:
    checks = []
    checks.append({
        "result": "pass" if intent else "fail",
        "message": "Action intent detected." if intent else "Action intent is unclear.",
    })
    checks.append({
        "result": "pass" if target_id else "fail",
        "message": "Target object ID detected." if target_id else "Target object ID is missing.",
    })
    checks.append({
        "result": "pass" if after else "fail",
        "message": "Proposed after value detected." if after else "Proposed after value is missing.",
    })
    checks.append({
        "result": "pass",
        "message": "Human approval is required before execution.",
    })
    return checks


def clarifying_question(
    intent: str | None,
    level: str,
    target_id: str | None,
    after: dict[str, Any],
    ambiguous_target: bool = False,
) -> str | None:
    if not intent:
        return "What exact Meta action should I prepare: rename, pause, change budget, targeting, or placement?"
    if not target_id:
        return f"Which target object ID ({level if level != 'unknown' else 'campaign, ad set, or ad'}) should this action apply to?"
    if ambiguous_target:
        return f"Please confirm the exact object: do you mean campaign, ad set, or ad {target_id}? I won't act on a bare number."
    if not after:
        return "What exact new value should I use for this action?"
    return None

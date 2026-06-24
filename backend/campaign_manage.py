"""Bulk management of EXISTING Meta campaigns from chat (pause / archive).

This module turns an operator instruction like "delete all campaigns created over a
week ago" or "pause the idle ones you created" into an approval-gated bulk action:

1. ``detect_manage_intent`` recognises a BULK manage/cleanup of EXISTING campaigns and
   maps the verb to an operator action ("pause" -> PAUSED, "archive"/"delete" ->
   ARCHIVED, which is reversible).
2. ``resolve_target_campaigns`` selects the matching campaigns from the live roster,
   applying the agent-created / idle / recency / name filters and the safety rules
   (never touch a currently-delivering campaign unless explicitly named).
3. ``build_manage_approval`` packages the selection into a ``manage_campaigns`` approval
   record; ``format_manage_answer`` renders the operator-facing list + approval prompt.

Execution (setting Meta status) lives in meta_execution.execute_manage_campaigns_approval.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# Verb -> operator action. Operator decision (verified): "delete/remove/archive/clean
# up/clear out/get rid of" => ARCHIVE (reversible); "pause/turn off/stop/disable/
# deactivate" => PAUSE.
_PAUSE_VERBS = (
    "pause",
    "turn off",
    "turn-off",
    "stop",
    "disable",
    "deactivate",
)
_ARCHIVE_VERBS = (
    "delete",
    "remove",
    "archive",
    "clean up",
    "cleanup",
    "clear out",
    "get rid of",
    "get rid",
)

# A bulk manage requires BOTH a manage verb AND a collection/filter signal so a single
# rename/budget tweak does NOT trip this path.
_COLLECTION_SIGNALS = (
    "campaigns",
    "all ",
    "these",
    "those",
    "the ones",
    "ones you",
    "idle",
    "inactive",
    "not running",
    "not active",
    "old",
    "older",
    "stale",
    "test",
    "draft",
    "drafts",
    "you created",
    "you made",
    "you built",
    "your campaigns",
    "agent created",
    "agent-created",
    "past week",
    "last week",
    "past one week",
    "older than",
    "more than a week",
    "over a week",
    "a week ago",
    "a week",
    "7 days",
    "seven days",
)

# Creation intent must NOT be treated as a manage request even though it can contain
# "campaign". "created" is deliberately allowed (it describes EXISTING campaigns here).
_CREATION_BLOCKERS = (
    "create a",
    "create campaign",
    "create campaigns",
    "launch",
    "build a",
    "build campaign",
    "set up",
    "setup",
    "new campaign",
)

_RECENCY_PHRASES = (
    "older than",
    "more than a week",
    "over a week",
    "past one week",
    "a week ago",
    "last week",
    "past week",
    "more than a week ago",
    "7 days",
    "seven days",
    "a week",
)

_AGENT_CREATED_PHRASES = (
    "you created",
    "you made",
    "you built",
    "your campaigns",
    "agent created",
    "agent-created",
    "the agent",
    "test",
    "draft",
)

_IDLE_PHRASES = (
    "idle",
    "inactive",
    "not running",
    "not active",
    "paused",
)

_INCLUDE_ACTIVE_PHRASES = (
    "including active",
    "include active",
    "even active",
    "running ones too",
    "running ones",
    "active ones too",
)

_ALL_AGENT_PHRASES = (
    "all your campaigns",
    "all the campaigns you",
    "all campaigns you",
    "all the test campaigns",
    "all test campaigns",
    "all your test",
)

_MAX_TARGETS = 50


def detect_manage_intent(message: str) -> dict[str, Any] | None:
    """Return {"action": "pause"|"archive"} for a BULK manage of EXISTING campaigns.

    Returns None for creation requests and single-target tweaks (rename/budget). A match
    requires BOTH a manage verb AND a collection/filter signal.
    """
    if not message:
        return None
    lower = message.lower()

    if any(blocker in lower for blocker in _CREATION_BLOCKERS):
        return None

    has_collection = any(signal in lower for signal in _COLLECTION_SIGNALS)
    if not has_collection:
        return None

    # Archive verbs win when present (delete/clean up is the stronger operator intent).
    if any(verb in lower for verb in _ARCHIVE_VERBS):
        return {"action": "archive"}
    if any(verb in lower for verb in _PAUSE_VERBS):
        return {"action": "pause"}
    return None


def agent_created_index() -> tuple[set[str], dict[str, str]]:
    """Collect campaign ids the agent created, plus id -> ISO timestamp.

    Reads executed ``create_paused_campaign_structure`` approvals from approval_store and
    walks ``executionLog`` entries for created campaign objects (level == "campaign").
    The timestamp is the entry's ``executedAt`` when present, else the approval's
    ``createdAt`` / ``executedAt``.
    """
    from . import approval_store

    ids: set[str] = set()
    created_at: dict[str, str] = {}
    try:
        approvals = approval_store.list_approval_requests()
    except Exception:  # noqa: BLE001 - storage absent in some tests/dev
        return ids, created_at

    for approval in approvals or []:
        if approval.get("actionType") != "create_paused_campaign_structure":
            continue
        approval_ts = approval.get("createdAt") or approval.get("executedAt")
        for entry in approval.get("executionLog", []) or []:
            entry_ts = entry.get("executedAt") or approval_ts
            result = entry.get("result") or {}
            for obj in result.get("created", []) or []:
                if obj.get("level") != "campaign":
                    continue
                cid = obj.get("id")
                if cid is None:
                    continue
                cid = str(cid)
                ids.add(cid)
                if entry_ts and cid not in created_at:
                    created_at[cid] = str(entry_ts)
    return ids, created_at


def _campaign_id(campaign: dict[str, Any]) -> str:
    return str(campaign.get("id") or "")


def _is_active(campaign: dict[str, Any]) -> bool:
    status = str(campaign.get("effective_status") or campaign.get("status") or "").upper()
    return status == "ACTIVE"


def _status_label(campaign: dict[str, Any]) -> str:
    return str(campaign.get("effective_status") or campaign.get("status") or "UNKNOWN")


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    # Meta uses "2026-04-26T10:00:00+0000"; ISO stamps use "+00:00" or "Z".
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
        return dt
    except (ValueError, TypeError):
        return None


def _name_tokens(message_lower: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", message_lower) if len(token) >= 4}


def _campaign_named(campaign: dict[str, Any], message_lower: str, message_tokens: set[str]) -> bool:
    """True when the campaign's name (or a distinctive token from it) appears verbatim."""
    name = str(campaign.get("name") or "").strip().lower()
    if not name:
        return False
    if name in message_lower:
        return True
    name_tokens = {tok for tok in re.split(r"[^a-z0-9]+", name) if len(tok) >= 4}
    # A distinctive token is one that isn't a generic word; require a real overlap.
    distinctive = name_tokens - {
        "draft",
        "test",
        "campaign",
        "vsl",
        "shahloai",
    }
    return bool(distinctive & message_tokens)


def resolve_target_campaigns(
    message: str,
    campaigns: list[dict[str, Any]],
    *,
    agent_ids: set[str],
    agent_created_at: dict[str, str],
    now_iso: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Select the campaigns matching the operator's bulk-manage instruction.

    Returns (selected campaigns, human-readable filter labels). See module docstring and
    the GOAL for the exact filter + safety semantics.
    """
    lower = (message or "").lower()
    message_tokens = _name_tokens(lower)
    labels: list[str] = []
    now = _parse_iso(now_iso) or datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    pool = [c for c in (campaigns or []) if isinstance(c, dict)]

    wants_agent_created = any(phrase in lower for phrase in _AGENT_CREATED_PHRASES)
    wants_idle = any(phrase in lower for phrase in _IDLE_PHRASES)
    wants_recency = any(phrase in lower for phrase in _RECENCY_PHRASES)
    include_active = any(phrase in lower for phrase in _INCLUDE_ACTIVE_PHRASES)
    wants_all_agent = any(phrase in lower for phrase in _ALL_AGENT_PHRASES)

    # Explicitly named campaigns are always eligible (even when ACTIVE).
    named = [c for c in pool if _campaign_named(c, lower, message_tokens)]
    named_ids = {_campaign_id(c) for c in named}

    selected = list(pool)

    if wants_agent_created:
        selected = [
            c
            for c in selected
            if _campaign_id(c) in agent_ids
            or str(c.get("name") or "").strip().upper().endswith("DRAFT")
        ]
        labels.append("created by the agent")

    if wants_idle:
        selected = [c for c in selected if not _is_active(c)]
        labels.append("idle (not active)")

    if wants_recency:
        recent_selected: list[dict[str, Any]] = []
        for c in selected:
            cid = _campaign_id(c)
            stamp = agent_created_at.get(cid) or c.get("start_time")
            ts = _parse_iso(stamp)
            # Conservative: no usable timestamp -> EXCLUDE when recency is requested.
            if ts is None:
                continue
            if ts < week_ago:
                recent_selected.append(c)
        selected = recent_selected
        labels.append("created over a week ago (interpreted as older-than-7-days)")

    # No specific filter recognised but the operator clearly means "all your campaigns" /
    # "all the test campaigns": fall back to the agent-created set.
    if not (wants_agent_created or wants_idle or wants_recency) and wants_all_agent:
        selected = [c for c in selected if _campaign_id(c) in agent_ids]
        labels.append("all campaigns created by the agent")

    # Always re-include explicitly named campaigns (operator override; bypasses filters).
    by_id = {_campaign_id(c): c for c in selected}
    for c in named:
        by_id.setdefault(_campaign_id(c), c)
    selected = list(by_id.values())

    # SAFETY: drop currently-delivering (ACTIVE) campaigns unless explicitly named OR the
    # operator clearly opted in to active ones.
    if not include_active:
        before = len(selected)
        selected = [c for c in selected if not _is_active(c) or _campaign_id(c) in named_ids]
        if len(selected) != before:
            labels.append("excluded currently-active campaigns (safety)")
    else:
        labels.append("including active campaigns (explicitly requested)")

    if named_ids:
        labels.append("included explicitly named campaign(s)")

    # Cap to 50 to keep the approval packet and Meta writes bounded.
    if len(selected) > _MAX_TARGETS:
        selected = selected[:_MAX_TARGETS]
        labels.append(f"capped to first {_MAX_TARGETS} campaigns")

    # De-duplicate label list while preserving order.
    labels = list(dict.fromkeys(labels))
    return selected, labels


def build_manage_approval(
    action: str,
    campaigns: list[dict[str, Any]],
    *,
    account_id: str,
    filter_labels: list[str],
    reason: str,
) -> dict[str, Any] | None:
    """Build a ``manage_campaigns`` approval record, or None when no campaigns match."""
    if not campaigns:
        return None

    status_value = "PAUSED" if action == "pause" else "ARCHIVED"
    after_campaigns = [
        {
            "id": _campaign_id(c),
            "name": str(c.get("name") or _campaign_id(c)),
            "effective_status": _status_label(c),
        }
        for c in campaigns
    ]

    active_count = sum(1 for c in campaigns if _is_active(c))
    checks: list[dict[str, Any]] = [
        {"result": "info", "message": f"{len(campaigns)} campaign(s) selected for {status_value}."},
    ]
    if active_count:
        checks.append(
            {
                "result": "warn",
                "message": f"{active_count} selected campaign(s) are currently ACTIVE.",
            }
        )
    guardrail_result = "warn" if active_count else "pass"

    now = datetime.now(timezone.utc)
    return {
        "id": f"approval_{now.strftime('%Y%m%dT%H%M%SZ')}",
        "actionType": "manage_campaigns",
        "target": {
            "level": "campaign_set",
            "id": account_id,
            "name": f"{len(campaigns)} campaigns",
        },
        "before": {},
        "after": {"status": status_value, "campaigns": after_campaigns},
        "reason": reason,
        "risk": "medium" if action == "archive" else "low",
        "expectedImpact": (
            f"Set {len(campaigns)} campaign(s) to {status_value}. "
            + ("Archiving is reversible." if action == "archive" else "Pausing stops delivery.")
        ),
        "guardrailResult": guardrail_result,
        "guardrailChecks": checks,
        "filterLabels": list(filter_labels or []),
        "executionMethod": "api",
        "requiresApproval": True,
        "status": "needs_review",
        "createdAt": now.isoformat(),
    }


def format_manage_answer(approval: dict[str, Any]) -> str:
    """HTML, emoji-structured operator-facing summary of a manage_campaigns approval."""
    after = approval.get("after") or {}
    status_value = str(after.get("status") or "PAUSED")
    campaigns = after.get("campaigns") or []
    is_archive = status_value == "ARCHIVED"
    verb = "Archive" if is_archive else "Pause"
    icon = "🗂" if is_archive else "⏸"

    lines = [f"{icon} <b>{verb} {len(campaigns)} campaign{'s' if len(campaigns) != 1 else ''}</b>"]

    explanation = (
        "Archiving sets each campaign to ARCHIVED (reversible — they can be reactivated later)."
        if is_archive
        else "Pausing sets each campaign to PAUSED (delivery stops; you can resume them)."
    )
    lines.append(explanation)

    labels = approval.get("filterLabels") or []
    if labels:
        lines.append("")
        lines.append("🔎 <b>Filters applied:</b> " + "; ".join(str(label) for label in labels) + ".")

    lines.append("")
    shown = campaigns[:15]
    for c in shown:
        name = str(c.get("name") or c.get("id") or "campaign")
        lines.append(f"• {name} — {c.get('effective_status', 'UNKNOWN')}")
    if len(campaigns) > len(shown):
        lines.append(f"… +{len(campaigns) - len(shown)} more")

    lines.append("")
    lines.append(
        "Reply <b>approve</b> to proceed (or tap Approve below); reply <b>reject</b> to cancel. "
        "Nothing changes until you confirm."
    )
    return "\n".join(lines)

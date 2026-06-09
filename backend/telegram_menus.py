"""Telegram inline menus and welcome copy.

The bot's main control surface: a button grid the operator taps instead of
typing slash commands. Buttons carry callback_data `menu:<target>` which
routers/telegram.py dispatches.
"""

from __future__ import annotations

import os
from typing import Any


def _dashboard_url() -> str:
    return os.getenv("PUBLIC_DASHBOARD_URL", "").strip()


# Labels for the persistent reply keyboard (docked under the text input). Tapping
# one sends its label as a normal message, which routers/telegram.py maps to an action.
BTN_KPIS = "📊 KPIs"
BTN_SUGGESTIONS = "🤖 Suggestions"
BTN_STATUS = "📈 Status"
BTN_ALERTS = "🚨 Alerts"
BTN_CAMPAIGNS = "📁 Campaigns"
BTN_PENDING = "📝 Pending Approvals"
BTN_ASK = "💬 Ask the agent"

# label (lowercased) -> menu action target handled by _handle_menu.
REPLY_BUTTON_ACTIONS: dict[str, str] = {
    BTN_KPIS.lower(): "kpis",
    BTN_SUGGESTIONS.lower(): "suggestions",
    BTN_STATUS.lower(): "status",
    BTN_ALERTS.lower(): "alerts",
    BTN_CAMPAIGNS.lower(): "campaigns",
    BTN_PENDING.lower(): "pending",
    BTN_ASK.lower(): "chat",
}


def main_reply_keyboard() -> dict[str, Any]:
    """Persistent buttons docked under the message input (always visible). The
    single dashboard entry point is the Telegram menu button (📊 Dashboard, set in
    telegram_setup.py); the live drill-downs live here instead of a redundant
    Analytics button."""
    return {
        "keyboard": [
            [{"text": BTN_KPIS}, {"text": BTN_SUGGESTIONS}],
            [{"text": BTN_STATUS}, {"text": BTN_ALERTS}],
            [{"text": BTN_CAMPAIGNS}, {"text": BTN_PENDING}],
            [{"text": BTN_ASK}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def main_menu_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 KPIs", "callback_data": "menu:kpis"},
                {"text": "🤖 Suggestions", "callback_data": "menu:suggestions"},
            ],
            [
                {"text": "📈 Status", "callback_data": "menu:status"},
                {"text": "🚨 Alerts", "callback_data": "menu:alerts"},
            ],
            [
                {"text": "💬 Ask the agent", "callback_data": "menu:chat"},
                {"text": "📊 Analytics", "callback_data": "menu:analytics"},
            ],
        ]
    }


def approval_stage_keyboard(stage: str, approval_id: str) -> dict[str, Any]:
    """Inline buttons for each step of the in-Telegram apply flow.

    needs_review -> approved (Dry run) -> dry_run (Apply live) -> done (no buttons).
    """
    if stage == "approved":
        rows = [[
            {"text": "🧪 Dry run", "callback_data": f"dryrun:{approval_id}"},
            {"text": "Reject", "callback_data": f"reject:{approval_id}"},
        ]]
    elif stage == "dry_run":
        rows = [[
            {"text": "⚠️ Apply live", "callback_data": f"applylive:{approval_id}"},
            {"text": "Cancel", "callback_data": f"cancel:{approval_id}"},
        ]]
    else:  # "done" / unknown -> clear the buttons
        rows = []
    return {"inline_keyboard": rows}


def _truncate(text: str, limit: int = 40) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _campaign_status_icon(campaign: dict[str, Any]) -> str:
    """Map a campaign's effective/status to a glanceable icon."""
    status = str(campaign.get("effective_status") or campaign.get("status") or "").upper()
    if status in {"ACTIVE", "IN_PROCESS", "PENDING_REVIEW", "PREAPPROVED"}:
        return "▶️"
    if status in {"PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "DISAPPROVED", "PENDING_BILLING_INFO"}:
        return "⏸"
    if status in {"DELETED", "ARCHIVED", "COMPLETED", "WITH_ISSUES"}:
        return "⏹"
    return "⏸"


# --- Task 3: live Campaigns drill-down (callback namespace `cmp`). ---
# Schemes: cmp:list, cmp:c:<campaign_id>, cmp:s:<adset_id>. Meta IDs are ~17
# digits, well under the 64-byte callback_data limit. Names go in button text
# (no limit) only.


def campaigns_list_keyboard(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """One button per campaign (cap 20), status-labeled, callback cmp:c:<id>."""
    rows = []
    for campaign in campaigns[:20]:
        cid = str(campaign.get("id") or "")
        if not cid:
            continue
        icon = _campaign_status_icon(campaign)
        label = f"{icon} {_truncate(str(campaign.get('name') or cid))}"
        rows.append([{"text": label, "callback_data": f"cmp:c:{cid}"}])
    return {"inline_keyboard": rows}


def campaign_adsets_keyboard(campaign_id: str, adsets: list[dict[str, Any]]) -> dict[str, Any]:
    """One button per ad set (cap 20), callback cmp:s:<id>, plus a Back button."""
    rows = []
    for adset in adsets[:20]:
        sid = str(adset.get("id") or "")
        if not sid:
            continue
        icon = _campaign_status_icon(adset)
        label = f"{icon} {_truncate(str(adset.get('name') or sid))}"
        rows.append([{"text": label, "callback_data": f"cmp:s:{sid}"}])
    rows.append([{"text": "⬅️ Back", "callback_data": "cmp:list"}])
    return {"inline_keyboard": rows}


def adset_ads_keyboard(adset_id: str, campaign_id: str) -> dict[str, Any]:
    """Leaf keyboard: just a Back button to the parent campaign's ad sets."""
    return {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": f"cmp:c:{campaign_id}"}]]}


# --- Task 4: Pending Approvals drill-down (callback namespace `apv`). ---
# Schemes: apv:list, apv:a:<approval_id>, apv:s:<approval_id>~<idx>. Ad sets in an
# approval have no id, so they are addressed by index after a `~` separator.


def pending_approvals_keyboard(approvals: list[dict[str, Any]]) -> dict[str, Any]:
    """One button per pending approval (cap 20), callback apv:a:<id>."""
    rows = []
    for approval in approvals[:20]:
        aid = str(approval.get("id") or "")
        if not aid:
            continue
        campaign = (approval.get("after") or {}).get("campaign") or {}
        label = _truncate(str(campaign.get("name") or approval.get("actionType") or aid))
        rows.append([{"text": f"📝 {label}", "callback_data": f"apv:a:{aid}"}])
    return {"inline_keyboard": rows}


def approval_adsets_keyboard(approval_id: str, adsets: list[dict[str, Any]]) -> dict[str, Any]:
    """One button per ad set (by index, cap 20), callback apv:s:<id>~<i>, plus Back."""
    rows = []
    for idx, adset in enumerate(adsets[:20]):
        label = _truncate(str(adset.get("name") or f"Ad set {idx + 1}"))
        rows.append([{"text": f"📦 {label}", "callback_data": f"apv:s:{approval_id}~{idx}"}])
    rows.append([{"text": "⬅️ Back", "callback_data": "apv:list"}])
    return {"inline_keyboard": rows}


def approval_adset_detail_keyboard(approval_id: str) -> dict[str, Any]:
    """Leaf keyboard: Back button to the approval's ad set list."""
    return {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": f"apv:a:{approval_id}"}]]}


def welcome_text() -> str:
    return (
        "👋 <b>Meta Ad Agent — control center</b>\n\n"
        "Tap a button below, or just text me a question "
        "(e.g. <i>which audience should I scale and why?</i>).\n\n"
        "I watch your account every 4 hours and send a KPI table here; "
        "new suggestions arrive with Approve buttons."
    )

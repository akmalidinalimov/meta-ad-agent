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
BTN_TEAM = "👥 Team"

# label (lowercased) -> menu action target handled by _handle_menu.
REPLY_BUTTON_ACTIONS: dict[str, str] = {
    BTN_KPIS.lower(): "kpis",
    BTN_SUGGESTIONS.lower(): "suggestions",
    BTN_STATUS.lower(): "status",
    BTN_ALERTS.lower(): "alerts",
    BTN_CAMPAIGNS.lower(): "campaigns",
    BTN_PENDING.lower(): "pending",
    BTN_ASK.lower(): "chat",
    BTN_TEAM.lower(): "team",
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
            [{"text": BTN_ASK}, {"text": BTN_TEAM}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def viewer_reply_keyboard() -> dict[str, Any]:
    """Read-only reply keyboard for viewer-role members: browse buttons only, no
    Ask/Team (those route to actions a viewer may not take)."""
    return {
        "keyboard": [
            [{"text": BTN_KPIS}, {"text": BTN_STATUS}],
            [{"text": BTN_ALERTS}, {"text": BTN_CAMPAIGNS}],
            [{"text": BTN_PENDING}],
        ],
        "resize_keyboard": True,
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
    """Leaf keyboard: open the rich creatives view in the web app (thumbnails +
    stats) when a dashboard URL is configured, plus a Back button to the parent
    campaign's ad sets."""
    rows: list[list[dict[str, Any]]] = []
    if adset_id:
        rows.append([{"text": "📸 Show creatives here", "callback_data": f"cmp:p:{adset_id}"}])
    url = _dashboard_url()
    if url and adset_id:
        sep = "&" if "?" in url else "?"
        creatives_url = f"{url}{sep}adset={adset_id}&campaign={campaign_id}"
        rows.append([{"text": "🖼 View creatives", "web_app": {"url": creatives_url}}])
    rows.append([{"text": "⬅️ Back", "callback_data": f"cmp:c:{campaign_id}"}])
    return {"inline_keyboard": rows}


# --- KPI digest scope picker (callback namespace `kpi`). ---
# Schemes: kpi:show, kpi:c:<campaign_id>, kpi:reset. The campaign name goes in the
# button text (full, lightly capped) so the operator can confirm the right campaign.


def kpi_panel_keyboard(campaigns: list[dict[str, Any]], selected_id: str | None = None) -> dict[str, Any]:
    """Pick which campaign the 4-hourly KPI digest reports on (or reset to account-wide).

    One button per campaign (cap 20) with a ✅ on the currently-watched one, plus a
    "Show KPIs now" shortcut and a "Reset to account-wide" button."""
    rows: list[list[dict[str, Any]]] = [[{"text": "📊 Show KPIs now", "callback_data": "kpi:show"}]]
    for campaign in campaigns[:20]:
        cid = str(campaign.get("id") or "")
        if not cid:
            continue
        icon = _campaign_status_icon(campaign)
        check = "✅ " if selected_id and cid == str(selected_id) else ""
        label = f"{check}{icon} {_truncate(str(campaign.get('name') or cid), 60)}"
        rows.append([{"text": label, "callback_data": f"kpi:c:{cid}"}])
    rows.append([{"text": "♻️ Reset to account-wide", "callback_data": "kpi:reset"}])
    return {"inline_keyboard": rows}


# --- Campaign-grouped browse pickers (Suggestions / Alerts / Pending) ----------
# Each of the three browse surfaces first shows a CAMPAIGN PICKER (one row per
# campaign that has items, with a count), then drills into that campaign's items.
# Namespaces: suggestions `sug`, alerts `alr`, pending approvals `apv`. The campaign
# id (~17 digits) stays well under the 64-byte callback_data limit; the no-campaign
# bucket uses the sentinel "none".


def _campaign_group_rows(groups: list[dict[str, Any]], callback_prefix: str, icon: str) -> list[list[dict[str, Any]]]:
    """One button per campaign group: '<icon> <name> · <count>' -> '<callback_prefix>:<id>'."""
    rows: list[list[dict[str, Any]]] = []
    for group in groups[:20]:
        cid = str(group.get("id") or "") or "none"
        name = _truncate(str(group.get("name") or "Other"), 48)
        rows.append([{"text": f"{icon} {name} · {int(group.get('count', 0))}", "callback_data": f"{callback_prefix}:{cid}"}])
    return rows


def suggestions_campaign_keyboard(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Campaign picker for 🤖 Suggestions. Tapping a campaign -> sug:c:<id>. The picker
    is re-rendered in place on drill (the suggestion cards arrive as separate messages),
    so no Back button is needed here."""
    return {"inline_keyboard": _campaign_group_rows(groups, "sug:c", "🤖")}


def alerts_campaign_keyboard(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Campaign picker for 🚨 Alerts. Tapping a campaign -> alr:c:<id>."""
    return {"inline_keyboard": _campaign_group_rows(groups, "alr:c", "🚨")}


def alerts_back_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "⬅️ Back to campaigns", "callback_data": "alr:list"}]]}


# --- Task 4: Pending Approvals drill-down (callback namespace `apv`). ---
# Schemes: apv:list (campaign picker), apv:gc:<campaign_id> (that campaign's approvals),
# apv:a:<approval_id>, apv:s:<approval_id>~<idx>. Ad sets in an approval have no id, so
# they are addressed by index after a `~` separator.


def pending_campaign_keyboard(groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Campaign picker for 📝 Pending Approvals. Tapping a campaign -> apv:gc:<id>."""
    return {"inline_keyboard": _campaign_group_rows(groups, "apv:gc", "📝")}


def pending_approvals_keyboard(approvals: list[dict[str, Any]]) -> dict[str, Any]:
    """One button per pending approval in a campaign (cap 20), callback apv:a:<id>,
    plus a Back button to the campaign picker."""
    rows = []
    for approval in approvals[:20]:
        aid = str(approval.get("id") or "")
        if not aid:
            continue
        campaign = (approval.get("after") or {}).get("campaign") or {}
        label = _truncate(str(campaign.get("name") or approval.get("actionType") or aid))
        rows.append([{"text": f"📝 {label}", "callback_data": f"apv:a:{aid}"}])
    rows.append([{"text": "⬅️ Back", "callback_data": "apv:list"}])
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


# --- Task 4: Team admin panel (callback namespace `team`). ---
# Schemes: team:add, team:list, team:remove:<key>, team:setrole:<key>~<role>.
# A member key is a numeric Telegram id or "u:<username>" — both stay well under
# the 64-byte callback_data limit alongside the short verbs and role names.


def team_panel_keyboard(members: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [[{"text": "➕ Add member", "callback_data": "team:add"}]]
    for m in members:
        key = str(m["userId"]) if m.get("userId") else "u:" + str(m.get("username"))
        label = (m.get("username") and "@" + m["username"]) or m.get("userId") or "?"
        if m["role"] == "owner":
            rows.append([{"text": f"👑 {label} (owner)", "callback_data": "team:list"}])
        else:
            other = "viewer" if m["role"] == "admin" else "admin"
            rows.append([
                {"text": f"{label} · {m['role']}", "callback_data": f"team:setrole:{key}~{other}"},
                {"text": "🗑", "callback_data": f"team:remove:{key}"},
            ])
    return {"inline_keyboard": rows}


def welcome_text() -> str:
    return (
        "👋 <b>Meta Ad Agent — control center</b>\n\n"
        "Tap a button below, or just text me a question "
        "(e.g. <i>which audience should I scale and why?</i>).\n\n"
        "I watch your account every 4 hours and send a KPI table here; "
        "new suggestions arrive with Approve buttons."
    )

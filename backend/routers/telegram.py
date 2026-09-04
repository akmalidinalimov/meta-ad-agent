"""Telegram operator routes — button-driven control center + command webhook."""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import access_control, approval_store, telegram_outbound
from ..api_models import TelegramTestMessageRequest
from ..approval_store import list_approval_requests
from ..execution_service import apply_live_sync, dry_run_sync
from ..telegram_commands import normalize_telegram_command
from ..telegram_digest import compose_kpi_digest_text
from ..telegram_menus import (
    REPLY_BUTTON_ACTIONS,
    alerts_back_keyboard,
    alerts_campaign_keyboard,
    kpi_panel_keyboard,
    adset_ads_keyboard,
    approval_adset_detail_keyboard,
    approval_adsets_keyboard,
    approval_stage_keyboard,
    campaign_adsets_keyboard,
    campaigns_list_keyboard,
    main_reply_keyboard,
    pending_approvals_keyboard,
    pending_campaign_keyboard,
    suggestions_campaign_keyboard,
    team_panel_keyboard,
    viewer_reply_keyboard,
    welcome_text,
)
from ..task_service import sync_task_with_approval
from ..telegram_service import (
    clamp_telegram_text,
    handle_telegram_shortcut,
    is_attention_question,
    send_telegram_reply,
    telegram_attention_text,
    telegram_command_allowed,
    telegram_status_text,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# --- RBAC: role gate for the Telegram surface --------------------------------
# Managers (owner/admin) get the full control surface; viewers may only browse
# (read-only buttons) and are blocked from any write action and from free-text
# requests; users with no role have no access at all.
_VIEWER_BLOCKED_ACTIONS = {
    "approve", "dryrun", "applylive", "cancel", "reject", "changes",
    "needs_changes", "agap", "manage", "view", "gcreate",
}
_NO_ACCESS = "🚫 You don't have access to this bot. You can leave."
_VIEWER_NOTICE = (
    "👀 You have <b>viewer</b> access — browse with the buttons below. "
    "I can't take requests or make changes for you."
)
# Reply-button labels + read-only commands a viewer is still allowed to use.
_VIEWER_FREE_TEXT_ALLOWED = {"start", "menu", "kpis", "suggestions", "status", "alerts"}


def _send(command: dict[str, Any], text: str, **kwargs: Any) -> dict[str, Any] | None:
    chat_id = command.get("chatId")
    if not chat_id:
        return None
    return telegram_outbound.send_telegram_message_sync(text, chat_id=chat_id, **kwargs)


def _edit_stage(callback: dict[str, Any], stage: str, approval_id: str) -> None:
    """Replace the tapped message's inline buttons with the next apply-flow stage."""
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    telegram_outbound.edit_message_reply_markup(chat_id, message.get("message_id"), approval_stage_keyboard(stage, approval_id))


# --- Campaign grouping for the browse surfaces (Suggestions / Alerts / Pending) ---
# All three group their items by campaign, show a campaign picker, then drill into the
# chosen campaign. These helpers are shared so the three surfaces stay consistent.


def _approval_campaign(approval: dict[str, Any]) -> tuple[str, str]:
    campaign = (approval.get("after") or {}).get("campaign") or {}
    cid = str(campaign.get("id") or "")
    name = str(campaign.get("name") or approval.get("actionType") or "Other")
    return cid, name


def _alert_campaign(alert: dict[str, Any]) -> tuple[str, str]:
    cid = str(alert.get("campaignId") or "")
    name = str(alert.get("campaignName") or alert.get("campaignId") or "Other")
    return cid, name


def _group_by_campaign(items: list[dict[str, Any]], extractor: Any) -> list[dict[str, Any]]:
    """Group items by campaign into ordered groups [{id, name, count, items}],
    busiest campaign first. Items with no campaign collapse into one 'Other' group."""
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        cid, name = extractor(item)
        key = cid or "none"
        group = groups.get(key)
        if group is None:
            group = {"id": cid, "name": name, "count": 0, "items": []}
            groups[key] = group
        group["count"] += 1
        group["items"].append(item)
    return sorted(groups.values(), key=lambda g: (-g["count"], str(g["name"]).lower()))


def _find_group(groups: list[dict[str, Any]], cid_tail: str) -> dict[str, Any] | None:
    """Resolve a 'sug:c:<id>' / 'apv:gc:<id>' tail back to its group ('none' sentinel
    matches the no-campaign bucket)."""
    want = "" if cid_tail == "none" else cid_tail
    return next((g for g in groups if (g["id"] or "") == want), None)


def _alert_severity_emoji(severity: Any) -> str:
    key = str(severity or "").lower()
    if key in {"high", "critical"}:
        return "❌"
    if key in {"medium", "warning", "warn"}:
        return "⚠️"
    return "ℹ️"


# --- Suggestions: campaign picker -> that campaign's suggestion cards ----------------


def _needs_review() -> list[dict[str, Any]]:
    return [a for a in list_approval_requests() if a.get("status") == "needs_review"]


def _suggestions_picker_text(groups: list[dict[str, Any]]) -> str:
    total = sum(g["count"] for g in groups)
    lines = [f"🤖 <b>Suggestions</b> ({total})"]
    if not groups:
        lines.append("\n✅ No suggestions waiting. I'll send new ones here as they come.")
    else:
        lines.append("\nPick a campaign to see its suggestions.")
    return "\n".join(lines)


def _open_suggestions(command: dict[str, Any]) -> dict[str, Any]:
    groups = _group_by_campaign(_needs_review(), _approval_campaign)
    _send(
        command,
        _suggestions_picker_text(groups),
        parse_mode="HTML",
        reply_markup=suggestions_campaign_keyboard(groups),
    )
    return {"ok": True, "telegram": command, "menu": "suggestions"}


def _handle_suggestions(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    """sug: callbacks — campaign picker (sug:list) and per-campaign drill (sug:c:<id>)."""
    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""
    groups = _group_by_campaign(_needs_review(), _approval_campaign)

    if tail.startswith("c:"):
        group = _find_group(groups, tail[2:])
        # Re-render the picker in place (counts stay current), then push the chosen
        # campaign's suggestions as their own actionable Approve/Dry-run cards.
        _edit(callback, _suggestions_picker_text(groups), suggestions_campaign_keyboard(groups))
        if not group:
            return {"ok": False, "telegram": command, "message": "no suggestions for campaign"}
        _send(command, f"🤖 <b>{html.escape(str(group['name']))}</b> — {group['count']} suggestion(s):", parse_mode="HTML")
        for approval in group["items"][:10]:
            telegram_outbound.send_approval_notification(approval)
        return {"ok": True, "telegram": command, "suggestions": group["id"] or "none", "sent": len(group["items"][:10])}

    # "sug:list" / default → (re)render the picker.
    if callback.get("message"):
        _edit(callback, _suggestions_picker_text(groups), suggestions_campaign_keyboard(groups))
        return {"ok": True, "telegram": command, "suggestions": "list"}
    return _open_suggestions(command)


# --- Alerts: campaign picker -> that campaign's alerts -------------------------------


def _campaign_alert_lines(alert: dict[str, Any]) -> list[str]:
    severity = str(alert.get("severity") or "info")
    title = str(alert.get("title") or "Untitled alert")
    out = [f"{_alert_severity_emoji(severity)} <b>{html.escape(severity)}</b> — {html.escape(title)}"]
    for action in (alert.get("recommendedActions") or [])[:3]:
        out.append(f"   • {html.escape(str(action))}")
    return out


def _alerts_picker_text(groups: list[dict[str, Any]]) -> str:
    total = sum(g["count"] for g in groups)
    lines = [f"🚨 <b>Alerts</b> ({total})"]
    if not groups:
        lines.append("\n✅ No monitoring alerts on the board. Run /monitoring or the dashboard check.")
    else:
        lines.append("\nPick a campaign to see its alerts.")
    return "\n".join(lines)


def _campaign_alerts_text(group: dict[str, Any]) -> str:
    lines = [f"🚨 <b>{html.escape(str(group['name']))}</b> — {group['count']} alert(s)", ""]
    for alert in group["items"][:10]:
        lines.extend(_campaign_alert_lines(alert))
    lines.append("")
    lines.append("🔒 Alerts are recommendations only; execution still needs approval.")
    return "\n".join(lines)


def _open_alerts(command: dict[str, Any]) -> dict[str, Any]:
    from ..monitoring_runner import list_monitoring_alerts

    groups = _group_by_campaign(list_monitoring_alerts(), _alert_campaign)
    _send(command, _alerts_picker_text(groups), parse_mode="HTML", reply_markup=alerts_campaign_keyboard(groups))
    return {"ok": True, "telegram": command, "menu": "alerts"}


def _handle_alerts(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    """alr: callbacks — campaign picker (alr:list) and per-campaign drill (alr:c:<id>)."""
    from ..monitoring_runner import list_monitoring_alerts

    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""
    groups = _group_by_campaign(list_monitoring_alerts(), _alert_campaign)

    if tail.startswith("c:"):
        group = _find_group(groups, tail[2:])
        if not group:
            _edit(callback, _alerts_picker_text(groups), alerts_campaign_keyboard(groups))
            return {"ok": False, "telegram": command, "message": "no alerts for campaign"}
        _edit(callback, _campaign_alerts_text(group), alerts_back_keyboard())
        return {"ok": True, "telegram": command, "alerts": group["id"] or "none"}

    # "alr:list" / default → (re)render the picker.
    _edit(callback, _alerts_picker_text(groups), alerts_campaign_keyboard(groups))
    return {"ok": True, "telegram": command, "alerts": "list"}


def _edit(callback: dict[str, Any], text: str, reply_markup: dict[str, Any] | None = None) -> None:
    """Rewrite the tapped message in place (drill-down navigation). Clamp to stay
    under Telegram's 4096-char limit, otherwise editMessageText is rejected and the
    tap appears to do nothing."""
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    telegram_outbound.edit_message_text(
        chat_id, message.get("message_id"), clamp_telegram_text(text), reply_markup=reply_markup, parse_mode="HTML"
    )


# --- Task 3: live Campaigns drill-down ---------------------------------------

def _live_account_sync() -> dict[str, Any]:
    """Fetch the account's campaigns/adsets/ads, preferring live Meta data and
    falling back to the last saved knowledge-base snapshot.

    Delegates to the shared ``meta_live.get_live_account`` cache (60s TTL) so the
    Telegram drill-down and the chat brain share one live-fetch path and fall
    back to the saved snapshot together. Returns
    {campaigns, adsets, ads, account_id, source}.
    """
    from ..knowledge_base import load_knowledge_base
    from ..meta_client import get_meta_config
    from ..meta_live import get_live_account

    knowledge = load_knowledge_base() or {}
    acct = asyncio.run(get_live_account(knowledge=knowledge))
    return {
        "campaigns": acct.campaigns,
        "adsets": acct.adsets,
        "ads": acct.ads,
        "adstudies": acct.adstudies,
        "saved_audiences": acct.saved_audiences,
        "account_id": get_meta_config().ad_account_id,
        "source": acct.source,
    }


def _campaign_status_label(entity: dict[str, Any]) -> str:
    status = str(entity.get("effective_status") or entity.get("status") or "UNKNOWN")
    return status.replace("_", " ").title()


def _campaigns_list_text(account: dict[str, Any]) -> str:
    campaigns = account.get("campaigns", [])
    lines = [f"📁 <b>Campaigns</b> ({len(campaigns)})"]
    if account.get("source") != "live":
        lines.append("<i>(as of last sync)</i>")
    if not campaigns:
        lines.append("\n— No campaigns found.")
    else:
        lines.append("\n👆 Tap a campaign to see its ad sets &amp; creatives.")
    return "\n".join(lines)


def _campaign_detail_text(
    campaign: dict[str, Any],
    adsets: list[dict[str, Any]],
    source: str,
    adstudies: list[dict[str, Any]] | None = None,
) -> str:
    from ..campaign_specific_analysis import ab_test_line

    name = html.escape(str(campaign.get("name") or campaign.get("id")))
    lines = [f"📁 <b>{name}</b>"]
    if source != "live":
        lines.append("🕒 <i>(as of last sync)</i>")
    lines.append(f"📌 Status: {html.escape(_campaign_status_label(campaign))}")
    if campaign.get("objective"):
        lines.append(f"🎯 Objective: {html.escape(str(campaign.get('objective')))}")
    if campaign.get("buying_type"):
        lines.append(f"🛒 Buying type: {html.escape(str(campaign.get('buying_type')))}")
    budget = campaign.get("daily_budget") or campaign.get("lifetime_budget")
    if budget:
        try:
            label = "Daily budget" if campaign.get("daily_budget") else "Lifetime budget"
            lines.append(f"💵 {label}: ${float(budget) / 100:,.2f}")
        except (TypeError, ValueError):
            pass
    ab = ab_test_line(campaign, adsets, adstudies or [])
    lines.append(f"🔬 A/B test: {html.escape(ab)}")
    lines.append(f"\n👥 <b>Ad sets / audiences</b> ({len(adsets)})")
    lines.append("👆 Tap one to see its creatives, ranked best-first.")
    return "\n".join(lines)


# Creative ranking + scoped fetch live in adset_creatives (shared with the web-app
# creatives view). Re-exported here under the historical names so existing call
# sites and tests keep working.
from ..adset_creatives import (  # noqa: E402
    fetch_adset_creatives_sync as _adset_creatives_sync,
    to_float as _to_float,
)


def _perf_line(perf: dict[str, Any]) -> str | None:
    if not perf.get("has_data"):
        return None
    bits = [
        f"💰 ${_to_float(perf.get('spend')):,.2f}",
        f"👁 {int(_to_float(perf.get('impressions'))):,}",
        f"🖱 {int(_to_float(perf.get('clicks'))):,}",
        f"📈 {_to_float(perf.get('ctr')):.2f}%",
    ]
    if perf.get("results") and perf.get("results_label"):
        bits.append(f"🎯 {int(_to_float(perf.get('results'))):,} {perf['results_label']}")
    return " · ".join(bits)


def _adset_detail_text(
    adset: dict[str, Any],
    ads: list[dict[str, Any]],
    account_id: str,
    campaign_id: str,
    source: str,
    audience_names: dict[str, str] | None = None,
) -> str:
    # Reuse the same config formatters chat uses so the two surfaces stay in sync.
    from ..campaign_specific_analysis import (
        format_custom_audiences,
        format_geo,
        format_interests,
        format_placements,
    )

    name = html.escape(str(adset.get("name") or adset.get("id")))
    lines = [f"📦 <b>{name}</b>"]
    if source != "live":
        lines.append("🕒 <i>(as of last sync)</i>")
    lines.append(f"📌 Status: {html.escape(_campaign_status_label(adset))}")
    budget = adset.get("daily_budget")
    if budget:
        try:
            lines.append(f"💵 Daily budget: ${float(budget) / 100:,.2f}")
        except (TypeError, ValueError):
            pass
    if adset.get("optimization_goal"):
        lines.append(f"🎯 Optimization: {html.escape(str(adset.get('optimization_goal')))}")

    targeting = adset.get("targeting") or {}
    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    if age_min is not None or age_max is not None:
        lines.append(f"👥 Age: {html.escape(f'{age_min or 18}-{age_max or 65}')}")
    geo = format_geo(targeting)
    if geo:
        lines.append(f"🌍 Geo: {html.escape(geo)}")
    interests = format_interests(targeting, 8)
    if interests:
        lines.append(f"🧩 Interests: {html.escape(interests)}")
    custom = format_custom_audiences(targeting, audience_names or {})
    if custom:
        lines.append(f"👤 Custom audiences: {html.escape(custom)}")
    placements = format_placements(targeting)
    if placements:
        lines.append(f"📍 Placements: {html.escape(placements)}")
    billing = adset.get("billing_event")
    bid = adset.get("bid_strategy")
    if billing or bid:
        billing_bid = f"{billing or 'n/a'} / {bid or 'n/a'}"
        lines.append(f"🧾 Billing/bid: {html.escape(billing_bid)}")
    if adset.get("is_dynamic_creative"):
        lines.append("♻️ Dynamic creative (DCO): on")

    any_data = any((ad.get("_perf") or {}).get("has_data") for ad in ads)
    header = "🏆 <b>Creatives — best performing first</b>" if any_data else "🎨 <b>Creatives</b>"
    lines.append(f"\n{header} ({len(ads)})")
    if not ads:
        lines.append("— No ads in this ad set yet.")
    elif not any_data:
        lines.append("<i>No delivery data yet — shown unranked.</i>")
    medals = ["🥇", "🥈", "🥉"]
    for index, ad in enumerate(ads[:10]):
        perf = ad.get("_perf") or {}
        creative = ad.get("creative") or {}
        rank = medals[index] if index < 3 else f"{index + 1}."
        lines.append("")
        lines.append(
            f"{rank} <b>{html.escape(str(ad.get('name') or 'Ad'))}</b>"
            f" — {html.escape(_campaign_status_label(ad))}"
        )
        perf_line = _perf_line(perf)
        if perf_line:
            lines.append(f"   {perf_line}")
        title = str(creative.get("title") or "").strip()
        if title:
            lines.append(f"   ✍️ {html.escape(title[:80])}{'…' if len(title) > 80 else ''}")
    # Thumbnails + full creative detail live in the web app (kept out of the chat
    # message so it stays well under Telegram's 4096-char limit).
    lines.append("\n🖼 Tap <b>View creatives</b> below for thumbnails &amp; full details.")
    if account_id and campaign_id:
        acct = account_id[4:] if account_id.startswith("act_") else account_id
        link = (
            "https://adsmanager.facebook.com/adsmanager/manage/ads"
            f"?act={html.escape(acct)}&amp;selected_campaign_ids={html.escape(str(campaign_id))}"
        )
        lines.append(f'🔗 <a href="{link}">Open in Ads Manager</a>')
    return "\n".join(lines)


def _open_campaigns_list(command: dict[str, Any]) -> dict[str, Any]:
    account = _live_account_sync()
    _send(
        command,
        _campaigns_list_text(account),
        parse_mode="HTML",
        reply_markup=campaigns_list_keyboard(account.get("campaigns", [])),
    )
    return {"ok": True, "telegram": command, "menu": "campaigns", "source": account.get("source")}


def _video_source_sync(video_id: str) -> dict[str, Any]:
    """Resolve a Meta video's playable source URL + permalink (sync wrapper)."""
    from ..meta_client import get_meta_config, get_video_source

    cfg = get_meta_config()
    if not (cfg.is_configured and video_id):
        return {}
    try:
        return asyncio.run(get_video_source(cfg, str(video_id)))
    except Exception:
        logger.exception("Video source fetch failed for %s", video_id)
        return {}


def _send_creative_media(command: dict[str, Any], adset_id: str) -> dict[str, Any]:
    """Send the ad set's top creatives as inline media: videos play on tap, images
    render as photos. Capped to the top few to stay responsive."""
    chat_id = command.get("chatId")
    ranked, _source = _adset_creatives_sync(adset_id)
    if not ranked:
        _send(command, "🎨 No creatives found for this ad set.")
        return {"ok": True, "telegram": command, "media": 0}

    _send(command, f"📸 <b>Top {min(3, len(ranked))} creatives</b> — tap a video to watch it.", parse_mode="HTML")
    medals = ["🥇", "🥈", "🥉"]
    sent = 0
    for index, ad in enumerate(ranked[:3]):
        creative = ad.get("creative") or {}
        perf = ad.get("_perf") or {}
        rank = medals[index] if index < 3 else f"{index + 1}."
        caption_lines = [f"{rank} <b>{html.escape(str(ad.get('name') or 'Creative'))}</b>"]
        perf_line = _perf_line(perf)
        if perf_line:
            caption_lines.append(perf_line)
        title = str(creative.get("title") or "").strip()
        if title:
            caption_lines.append(f"✍️ {html.escape(title[:120])}")
        caption = "\n".join(caption_lines)[:1024]
        thumb = creative.get("image_url") or creative.get("thumbnail_url")
        video_id = creative.get("video_id")
        delivered = False
        if video_id:
            src = _video_source_sync(str(video_id))
            video_url = src.get("source")
            # Meta often returns a RELATIVE permalink (e.g. "/reel/123/"); Telegram URL
            # buttons require an absolute http(s) URL or the whole send is rejected (400).
            watch = str(src.get("permalink_url") or "").strip()
            if watch.startswith("/"):
                watch = "https://www.facebook.com" + watch
            if not watch.startswith("http"):
                watch = f"https://www.facebook.com/watch/?v={video_id}"
            if video_url and chat_id:
                resp = telegram_outbound.send_video(chat_id, video_url, caption=caption, parse_mode="HTML")
                delivered = bool(resp.get("ok"))
            if not delivered and chat_id and thumb:
                # Fallback: show the thumbnail with a Watch button to the video page.
                markup = {"inline_keyboard": [[{"text": "▶️ Watch video", "url": watch}]]}
                resp = telegram_outbound.send_photo(chat_id, thumb, caption=caption, parse_mode="HTML", reply_markup=markup)
                delivered = bool(resp.get("ok"))
        elif thumb and chat_id:
            resp = telegram_outbound.send_photo(chat_id, thumb, caption=caption, parse_mode="HTML")
            delivered = bool(resp.get("ok"))
        if delivered:
            sent += 1
    if not sent:
        _send(command, "⚠️ Couldn't load the creative media. Open <b>View creatives</b> for the full gallery.", parse_mode="HTML")
    return {"ok": True, "telegram": command, "media": sent}


# --- Task 5: guided campaign creation (audience -> creatives -> propose) ------


def _guided_creative_keyboard(creative_id: str, selected: list[str]) -> dict[str, Any]:
    """The single tap-to-toggle button shown under each creative in the picker."""
    from .. import guided_campaign

    return {
        "inline_keyboard": [[
            {
                "text": guided_campaign.creative_toggle_label(creative_id, selected),
                "callback_data": f"gcreate:cre:toggle:{creative_id}",
            }
        ]]
    }


def _render_guided_creatives(command: dict[str, Any], op_key: str) -> dict[str, Any]:
    """Render the account's top creatives as inline media, each with a SELECT
    toggle, then a control message to confirm. Reuses the same video/photo
    fallback ladder as ``_send_creative_media``. If nothing is synced, skip to
    finalize (the builder falls back to the account defaults)."""
    from .. import guided_campaign
    from ..knowledge_base import load_knowledge_base
    from ..pending_context_store import get_pending

    chat_id = command.get("chatId")
    rows = guided_campaign.top_creatives_for_selection(load_knowledge_base(), limit=8)
    if not rows:
        _send(command, "No creatives synced yet — I'll use the account's defaults.")
        out = guided_campaign.finalize(op_key)
        _send(command, out["text"], parse_mode="HTML", reply_markup=out.get("reply_markup"))
        return {"ok": True, "telegram": command, "guided": "finalize_no_creatives"}

    pending = get_pending(op_key) or {}
    selected = list((pending.get("guided") or {}).get("selectedCreatives") or [])

    sent = 0
    for row in rows[:8]:
        cid = row["id"]
        caption = row.get("name") or "Creative"
        toggle = _guided_creative_keyboard(cid, selected)
        video_id = row.get("videoId")
        thumb = row.get("thumb")
        delivered = False
        if video_id:
            src = _video_source_sync(str(video_id))
            video_url = src.get("source")
            watch = str(src.get("permalink_url") or "").strip()
            if watch.startswith("/"):
                watch = "https://www.facebook.com" + watch
            if not watch.startswith("http"):
                watch = f"https://www.facebook.com/watch/?v={video_id}"
            if video_url and chat_id:
                resp = telegram_outbound.send_video(chat_id, video_url, caption=caption, reply_markup=toggle)
                delivered = bool(resp.get("ok"))
            if not delivered and chat_id and thumb:
                resp = telegram_outbound.send_photo(chat_id, thumb, caption=caption, reply_markup=toggle)
                if resp.get("ok"):
                    delivered = True
                    telegram_outbound.send_telegram_message_sync(
                        f"▶️ Watch: {watch}", chat_id=chat_id,
                    )
        elif thumb and chat_id:
            resp = telegram_outbound.send_photo(chat_id, thumb, caption=caption, reply_markup=toggle)
            delivered = bool(resp.get("ok"))
        else:
            _send(command, caption + " (no preview)", reply_markup=toggle)
            delivered = True
        if delivered:
            sent += 1

    _send(
        command,
        "Tap ➕ on the creatives you want, then confirm.",
        reply_markup={"inline_keyboard": [
            [{"text": "✅ Use selected", "callback_data": "gcreate:cre:done"}],
            [{"text": "⚡ Use top 5", "callback_data": "gcreate:cre:auto"}],
        ]},
    )
    return {"ok": True, "telegram": command, "guided": "creatives", "rendered": sent}


def _handle_guided(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    """Transport handler for the guided-creation inline callbacks. Parses the tail
    after ``gcreate:`` and dispatches to the guided_campaign state machine; the
    state logic lives there, this only moves messages/keyboards."""
    from .. import guided_campaign
    from ..knowledge_base import load_knowledge_base
    from ..pending_context_store import get_pending, operator_key

    op_key = operator_key(telegram_chat_id=command.get("chatId"))
    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""  # strip leading "gcreate:"

    # --- audience step -------------------------------------------------------
    if tail in ("aud:proven", "aud:new"):
        choice = tail.split(":", 1)[1]
        out = guided_campaign.handle_audience_choice(op_key, choice)
        if out.get("next") == "render_creatives":
            return _render_guided_creatives(command, op_key)
        _send(command, out["text"], parse_mode="HTML")
        return {"ok": True, "telegram": command, "guided": "audience"}

    if tail == "aud:input":
        out = guided_campaign.handle_audience_choice(op_key, "input")
        _send(command, out["text"])
        return {"ok": True, "telegram": command, "guided": "audience_input"}

    # --- creative step -------------------------------------------------------
    if tail.startswith("cre:toggle:"):
        cid = tail[len("cre:toggle:"):]
        selected = guided_campaign.handle_creative_toggle(op_key, cid)
        message = callback.get("message") or {}
        telegram_outbound.edit_message_reply_markup(
            (message.get("chat") or {}).get("id"),
            message.get("message_id"),
            _guided_creative_keyboard(cid, selected),
        )
        return {"ok": True, "telegram": command, "guided": "toggle", "selected": selected}

    if tail == "cre:auto":
        # Select the account's top 5 creatives, then finalize as if "done".
        for row in guided_campaign.top_creatives_for_selection(load_knowledge_base(), limit=5):
            current = (get_pending(op_key) or {}).get("guided") or {}
            if row["id"] not in (current.get("selectedCreatives") or []):
                guided_campaign.handle_creative_toggle(op_key, row["id"])
        out = guided_campaign.finalize(op_key)
        _send(command, out["text"], parse_mode="HTML", reply_markup=out.get("reply_markup"))
        return {"ok": True, "telegram": command, "guided": "auto"}

    if tail == "cre:done":
        out = guided_campaign.finalize(op_key)
        _send(command, out["text"], parse_mode="HTML", reply_markup=out.get("reply_markup"))
        return {"ok": True, "telegram": command, "guided": "done"}

    _send(command, "That step expired. Say \"create a campaign\" to start over.")
    return {"ok": False, "telegram": command, "guided": "unknown"}


def _handle_campaigns(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""
    if tail.startswith("p:"):
        return _send_creative_media(command, tail[2:])
    account = _live_account_sync()
    campaigns = account.get("campaigns", [])
    adsets = account.get("adsets", [])
    source = account.get("source", "snapshot")
    adstudies = account.get("adstudies") or []
    audience_names = {
        str(a["id"]): a.get("name", "")
        for a in (account.get("saved_audiences") or [])
        if isinstance(a, dict) and a.get("id") is not None
    }

    if tail == "list":
        _edit(callback, _campaigns_list_text(account), campaigns_list_keyboard(campaigns))
        return {"ok": True, "telegram": command, "campaigns": "list"}

    if tail.startswith("c:"):
        cid = tail[2:]
        campaign = next((c for c in campaigns if str(c.get("id")) == cid), None)
        if not campaign:
            _edit(callback, "This campaign is no longer available.", campaigns_list_keyboard(campaigns))
            return {"ok": False, "telegram": command, "message": "campaign not found"}
        child = [a for a in adsets if str(a.get("campaign_id")) == cid]
        _edit(callback, _campaign_detail_text(campaign, child, source, adstudies), campaign_adsets_keyboard(cid, child))
        return {"ok": True, "telegram": command, "campaign": cid}

    if tail.startswith("s:"):
        sid = tail[2:]
        adset = next((a for a in adsets if str(a.get("id")) == sid), None)
        if not adset:
            _edit(callback, "This ad set is no longer available.", campaigns_list_keyboard(campaigns))
            return {"ok": False, "telegram": command, "message": "adset not found"}
        campaign_id = str(adset.get("campaign_id") or "")
        ranked_ads, ads_source = _adset_creatives_sync(sid)
        _edit(
            callback,
            _adset_detail_text(adset, ranked_ads, account.get("account_id", ""), campaign_id, ads_source, audience_names),
            adset_ads_keyboard(sid, campaign_id),
        )
        return {"ok": True, "telegram": command, "adset": sid}

    _edit(callback, _campaigns_list_text(account), campaigns_list_keyboard(campaigns))
    return {"ok": True, "telegram": command, "campaigns": "list"}


# --- KPI digest scope picker (callback namespace `kpi`) ----------------------
# Lets the operator pick which campaign the 4-hourly KPI digest reports on, or reset
# to the account-wide digest. The selection is global (the digest has one destination,
# the admin chat) and is read by telegram_digest.compose_kpi_digest_text.


def _kpi_panel_text(selection: dict[str, Any] | None) -> str:
    if selection and selection.get("campaignId"):
        name = html.escape(str(selection.get("campaignName") or selection["campaignId"]))
        scope = f"📌 Now watching: <b>{name}</b>"
    else:
        scope = "📌 Now watching: <b>account-wide (all campaigns)</b>"
    return (
        "<b>📊 KPI digest scope</b>\n\n"
        f"{scope}\n\n"
        "Pick a campaign below to get the 4-hourly KPI digest for just that campaign, "
        "tap <b>Reset</b> for the whole account, or <b>Show KPIs now</b> for the current digest."
    )


def _open_kpi_panel(command: dict[str, Any]) -> dict[str, Any]:
    """Send the KPI scope picker as a new message (from the KPI menu / reply button)."""
    from ..kpi_digest_campaign_store import load_kpi_digest_campaign

    account = _live_account_sync()
    campaigns = account.get("campaigns", [])
    selection = load_kpi_digest_campaign()
    selected_id = selection["campaignId"] if selection else None
    _send(
        command,
        _kpi_panel_text(selection),
        parse_mode="HTML",
        reply_markup=kpi_panel_keyboard(campaigns, selected_id),
    )
    return {"ok": True, "telegram": command, "kpi": "panel"}


def _handle_kpi(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    """kpi: callbacks — show the digest now, pin a campaign, or reset to account-wide."""
    from ..kpi_digest_campaign_store import (
        clear_kpi_digest_campaign,
        load_kpi_digest_campaign,
        set_kpi_digest_campaign,
    )

    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""

    # "Show KPIs now" is read-only — any role may use it.
    if tail == "show":
        _send(command, compose_kpi_digest_text(), parse_mode="HTML")
        return {"ok": True, "telegram": command, "kpi": "show"}

    # Pinning / resetting the digest scope is a config write — managers only.
    role = access_control.role_for(command.get("userId") or command.get("chatId"), command.get("username"))
    if (tail.startswith("c:") or tail == "reset") and not access_control.is_manager(role):
        _send(command, _VIEWER_NOTICE, parse_mode="HTML", reply_markup=viewer_reply_keyboard())
        return {"ok": False, "telegram": command, "denied": "viewer_action"}

    actor = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"
    account = _live_account_sync()
    campaigns = account.get("campaigns", [])

    if tail == "reset":
        clear_kpi_digest_campaign()
        _edit(callback, _kpi_panel_text(None), kpi_panel_keyboard(campaigns, None))
        return {"ok": True, "telegram": command, "kpi": "reset"}

    if tail.startswith("c:"):
        cid = tail[2:]
        campaign = next((c for c in campaigns if str(c.get("id")) == cid), None)
        if not campaign:
            selection = load_kpi_digest_campaign()
            selected_id = selection["campaignId"] if selection else None
            _edit(
                callback,
                "⚠️ That campaign is no longer available.\n\n" + _kpi_panel_text(selection),
                kpi_panel_keyboard(campaigns, selected_id),
            )
            return {"ok": False, "telegram": command, "message": "campaign not found"}
        set_kpi_digest_campaign(cid, str(campaign.get("name") or cid), selected_by=actor)
        selection = load_kpi_digest_campaign()
        _edit(callback, _kpi_panel_text(selection), kpi_panel_keyboard(campaigns, cid))
        return {"ok": True, "telegram": command, "kpi": "set", "campaign": cid}

    # Default: (re)render the panel.
    selection = load_kpi_digest_campaign()
    selected_id = selection["campaignId"] if selection else None
    if callback.get("message"):
        _edit(callback, _kpi_panel_text(selection), kpi_panel_keyboard(campaigns, selected_id))
    else:
        _send(command, _kpi_panel_text(selection), parse_mode="HTML", reply_markup=kpi_panel_keyboard(campaigns, selected_id))
    return {"ok": True, "telegram": command, "kpi": "panel"}


# --- Task 4: Pending Approvals drill-down ------------------------------------

def _pending_approvals() -> list[dict[str, Any]]:
    return [a for a in list_approval_requests() if a.get("status") == "needs_review"]


def _pending_picker_text(groups: list[dict[str, Any]]) -> str:
    total = sum(g["count"] for g in groups)
    lines = [f"📝 <b>Pending Approvals</b> ({total})"]
    if not groups:
        lines.append("\n✅ Nothing waiting for review.")
    else:
        lines.append("\nPick a campaign to see its approvals.")
    return "\n".join(lines)


def _campaign_approvals_text(group: dict[str, Any]) -> str:
    lines = [f"📝 <b>{html.escape(str(group['name']))}</b> — {group['count']} approval(s)"]
    lines.append("\nTap one to review its ad sets.")
    return "\n".join(lines)


def _approval_detail_text(approval: dict[str, Any], adsets: list[dict[str, Any]]) -> str:
    campaign = (approval.get("after") or {}).get("campaign") or {}
    name = html.escape(str(campaign.get("name") or approval.get("actionType") or approval.get("id")))
    lines = [f"📝 <b>{name}</b>"]
    if approval.get("risk"):
        lines.append(f"Risk: {html.escape(str(approval.get('risk')))}")
    lines.append(f"\nAd sets ({len(adsets)}): tap one for full detail.")
    return "\n".join(lines)


def _approval_adset_text(approval: dict[str, Any], adset: dict[str, Any], idx: int) -> str:
    name = html.escape(str(adset.get("name") or f"Ad set {idx + 1}"))
    lines = [f"📦 <b>{name}</b>"]
    lines.append(f"Status: {html.escape(str(adset.get('status') or 'PAUSED'))}")
    budget = adset.get("daily_budget")
    if budget:
        try:
            lines.append(f"Daily budget: ${float(budget) / 100:,.2f}")
        except (TypeError, ValueError):
            pass
    if adset.get("optimization_goal"):
        lines.append(f"Optimization: {html.escape(str(adset.get('optimization_goal')))}")
    targeting = adset.get("targeting") or {}
    if targeting:
        geos = (targeting.get("geo_locations") or {}).get("countries") or []
        if geos:
            lines.append(f"Targeting: {html.escape(', '.join(str(g) for g in geos[:8]))}")
    ads = adset.get("ads") or []
    lines.append(f"\n<b>Ads ({len(ads)})</b>")
    if not ads:
        lines.append("No ads defined.")
    for ad in ads[:10]:
        lines.append(
            f"• <b>{html.escape(str(ad.get('name') or 'Ad'))}</b> — {html.escape(str(ad.get('status') or 'PAUSED'))}"
        )
        if ad.get("creativeId"):
            lines.append(f"  creativeId: {html.escape(str(ad.get('creativeId')))}")
    return "\n".join(lines)


def _open_pending_list(command: dict[str, Any]) -> dict[str, Any]:
    groups = _group_by_campaign(_pending_approvals(), _approval_campaign)
    _send(
        command,
        _pending_picker_text(groups),
        parse_mode="HTML",
        reply_markup=pending_campaign_keyboard(groups),
    )
    return {"ok": True, "telegram": command, "menu": "pending"}


def _handle_pending(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""
    approvals = _pending_approvals()

    if tail == "list" or not tail:
        groups = _group_by_campaign(approvals, _approval_campaign)
        _edit(callback, _pending_picker_text(groups), pending_campaign_keyboard(groups))
        return {"ok": True, "telegram": command, "pending": "list"}

    if tail.startswith("gc:"):
        groups = _group_by_campaign(approvals, _approval_campaign)
        group = _find_group(groups, tail[3:])
        if not group:
            _edit(callback, _pending_picker_text(groups), pending_campaign_keyboard(groups))
            return {"ok": False, "telegram": command, "message": "no approvals for campaign"}
        _edit(callback, _campaign_approvals_text(group), pending_approvals_keyboard(group["items"]))
        return {"ok": True, "telegram": command, "pending": "campaign", "campaign": group["id"] or "none"}

    if tail.startswith("a:"):
        aid = tail[2:]
        approval = next((a for a in approvals if str(a.get("id")) == aid), None)
        if not approval:
            _edit(callback, "This approval is no longer pending.", pending_approvals_keyboard(approvals))
            return {"ok": False, "telegram": command, "message": "not pending"}
        adsets = (approval.get("after") or {}).get("adsets") or []
        _edit(callback, _approval_detail_text(approval, adsets), approval_adsets_keyboard(aid, adsets))
        return {"ok": True, "telegram": command, "approval": aid}

    if tail.startswith("s:"):
        rest = tail[2:]
        aid, _, idx_raw = rest.partition("~")
        approval = next((a for a in approvals if str(a.get("id")) == aid), None)
        if not approval:
            _edit(callback, "This approval is no longer pending.", pending_approvals_keyboard(approvals))
            return {"ok": False, "telegram": command, "message": "not pending"}
        adsets = (approval.get("after") or {}).get("adsets") or []
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            idx = -1
        if idx < 0 or idx >= len(adsets):
            _edit(callback, "That ad set is no longer available.", approval_adsets_keyboard(aid, adsets))
            return {"ok": False, "telegram": command, "message": "adset index out of range"}
        _edit(callback, _approval_adset_text(approval, adsets[idx], idx), approval_adset_detail_keyboard(aid))
        return {"ok": True, "telegram": command, "approval": aid, "adset": idx}

    groups = _group_by_campaign(approvals, _approval_campaign)
    _edit(callback, _pending_picker_text(groups), pending_campaign_keyboard(groups))
    return {"ok": True, "telegram": command, "pending": "list"}


# --- Task 4: Team admin panel (managers only) --------------------------------

def _team_text(members: list[dict[str, Any]]) -> str:
    lines = [f"👥 <b>Team</b> ({len(members)})"]
    if not members:
        lines.append("\nNo members yet.")
        return "\n".join(lines)
    lines.append("")
    for m in members:
        username = m.get("username")
        ident = ("@" + str(username)) if username else str(m.get("userId") or "?")
        role = str(m.get("role") or "viewer")
        if role == "owner":
            lines.append(f"👑 {html.escape(ident)} — <b>owner</b>")
        else:
            lines.append(f"• {html.escape(ident)} — {html.escape(role)}")
    lines.append("\n👆 Tap a member to flip their role, 🗑 to remove, or ➕ to add.")
    return "\n".join(lines)


def _open_team_panel(command: dict[str, Any]) -> dict[str, Any]:
    from .. import members_store

    members = members_store.list_members()
    _send(command, _team_text(members), parse_mode="HTML", reply_markup=team_panel_keyboard(members))
    return {"ok": True, "telegram": command, "team": "list"}


def _handle_team(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    from .. import members_store
    from ..pending_context_store import operator_key, set_pending

    tail = command.get("approvalId") or ""
    verb, _, rest = tail.partition(":")
    actor = str(command.get("userId") or command.get("chatId"))
    if verb == "add":
        set_pending(operator_key(telegram_chat_id=command.get("chatId")), {"kind": "team_add"})
        _send(
            command,
            "Send the new member as <code>@username admin</code> or <code>123456 viewer</code>.",
            parse_mode="HTML",
        )
        return {"ok": True, "telegram": command, "team": "add_prompt"}
    if verb == "remove":
        try:
            members_store.remove_member(rest, actor=actor)
            _send(command, "✅ Removed.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        except KeyError:
            _send(command, "That member is no longer on the team.")
        return _open_team_panel(command)
    if verb == "setrole":
        key, _, role = rest.partition("~")
        try:
            members_store.set_role(key, role, actor=actor)
            _send(command, f"✅ Role set to {role}.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        except KeyError:
            _send(command, "Member not found.")
        return _open_team_panel(command)
    return _open_team_panel(command)


def _handle_menu(command: dict[str, Any], target: str) -> dict[str, Any]:
    if target == "kpis":
        return _open_kpi_panel(command)
    elif target == "suggestions":
        return _open_suggestions(command)
    elif target == "status":
        _send(command, telegram_status_text(), parse_mode="HTML")
    elif target == "alerts":
        return _open_alerts(command)
    elif target == "campaigns":
        return _open_campaigns_list(command)
    elif target == "pending":
        return _open_pending_list(command)
    elif target == "team":
        return _open_team_panel(command)
    elif target == "chat":
        _send(command, '💬 Just text me your question — e.g. "what are my best creatives right now?"')
    elif target == "analytics":
        url = os.getenv("PUBLIC_DASHBOARD_URL", "").strip()
        _send(command, f"📊 Open your dashboard: {url}" if url else "Dashboard URL is not configured yet.")
    else:  # "menu" or unknown -> show the main menu
        _send(command, welcome_text(), parse_mode="HTML", reply_markup=main_reply_keyboard())
    return {"ok": True, "telegram": command, "menu": target}


@router.post("/api/telegram/command")
def telegram_agent_command(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("TELEGRAM_COMMAND_SECRET", "").strip()
    provided_secret = str(
        payload.get("secret")
        or request.headers.get("x-telegram-agent-secret")
        # Telegram's native webhook secret header (setWebhook secret_token).
        or request.headers.get("x-telegram-bot-api-secret-token")
        or ""
    ).strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid Telegram command secret.")

    command = normalize_telegram_command(payload)

    # --- RBAC gate -----------------------------------------------------------
    # Resolve the caller's role from the managed members store. None == no access.
    role = access_control.role_for(command.get("userId") or command.get("chatId"), command.get("username"))
    if role is None:
        _send(command, _NO_ACCESS)
        return {"ok": False, "telegram": command, "denied": "no_access"}

    action = command.get("action")
    if not access_control.is_manager(role):
        # Viewers may browse but never take a write action or open the team panel.
        if action in _VIEWER_BLOCKED_ACTIONS or (action or "").startswith("team"):
            _send(command, _VIEWER_NOTICE, parse_mode="HTML", reply_markup=viewer_reply_keyboard())
            return {"ok": False, "telegram": command, "denied": "viewer_action"}

    # Acknowledge any button tap immediately so Telegram stops the loading spinner.
    callback = payload.get("callback_query") or {}
    if callback.get("id"):
        telegram_outbound.answer_callback_query(callback.get("id"))

    action = command.get("action")
    approval_id = command.get("approvalId")
    actor = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"

    if action == "approve" and approval_id:
        existing = next((a for a in list_approval_requests() if a.get("id") == approval_id), None)
        # Bulk-manage approvals apply IMMEDIATELY on Approve (archive/pause is the whole
        # action — no separate dry-run/apply-live ladder like campaign creation).
        if existing and existing.get("actionType") == "manage_campaigns":
            try:
                approval_store.approve_request(approval_id, approved_by=actor)
            except KeyError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            from ..pending_context_store import clear_pending as _clear, operator_key as _opkey

            exec_result = apply_live_sync(approval_id)
            _clear(_opkey(telegram_chat_id=command.get("chatId")))
            telegram_outbound.edit_message_reply_markup(
                (callback.get("message") or {}).get("chat", {}).get("id"),
                (callback.get("message") or {}).get("message_id"),
                {"inline_keyboard": []},
            )
            if not exec_result.get("ok"):
                msg = f"❌ Could not apply: {exec_result.get('error') or 'unknown error'}"
                _send(command, msg)
                return {"ok": False, "telegram": command, "message": "manage apply failed"}
            inner = exec_result.get("result") or {}
            changed = inner.get("changed") or []
            status_value = inner.get("status") or (existing.get("after") or {}).get("status") or "updated"
            verb = "Archived" if status_value == "ARCHIVED" else "Paused"
            msg = f"✅ {verb} {len(changed)} campaign(s)."
            _send(command, msg)
            return {"ok": True, "telegram": command, "managed": True, "changed": changed}

        try:
            approval = approval_store.approve_request(approval_id, approved_by=actor)
            sync_task_with_approval(approval_id, "approved", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        _edit_stage(callback, "approved", approval_id)
        message = "✅ Approved. Tap 🧪 Dry run to preview, then ⚠️ Apply live to create it (PAUSED) in Meta."
        return {"ok": True, "telegram": command, "approval": approval, "message": message, "reply": send_telegram_reply(command, message)}

    if action == "dryrun" and approval_id:
        result = dry_run_sync(approval_id)
        if not result.get("ok"):
            _send(command, f"Dry run failed: {result.get('error') or 'unknown error'}")
            return {"ok": False, "telegram": command, "message": "dry run failed"}
        would = (result.get("result") or {}).get("wouldCreate") or {}
        campaign = html.escape(str((would.get("campaign") or {}).get("name", "campaign")))
        adsets = len(would.get("adsets") or [])
        _send(
            command,
            f"🧪 <b>Dry run</b> — would create <b>{campaign}</b> + {adsets} ad set(s), all PAUSED (no spend).\n"
            "Tap ⚠️ Apply live to create it in Meta.",
            parse_mode="HTML",
        )
        _edit_stage(callback, "dry_run", approval_id)
        return {"ok": True, "telegram": command, "dryRun": True}

    if action == "applylive" and approval_id:
        result = apply_live_sync(approval_id)
        if not result.get("ok"):
            _send(command, f"❌ Meta rejected the write: {result.get('error') or 'unknown error'}")
            return {"ok": False, "telegram": command, "message": "apply failed"}
        created = (result.get("result") or {}).get("created") or []
        campaign = next((c for c in created if c.get("level") == "campaign"), {})
        name = html.escape(str(campaign.get("name", "campaign")))
        _send(
            command,
            f"✅ Created in Meta as <b>PAUSED</b>: {name} (id {campaign.get('id')}).\n"
            "Review in Ads Manager — nothing spends until you enable delivery.",
            parse_mode="HTML",
        )
        _edit_stage(callback, "done", approval_id)
        return {"ok": True, "telegram": command, "applied": True}

    if action == "cancel" and approval_id:
        _edit_stage(callback, "approved", approval_id)
        _send(command, "Cancelled — still approved. Tap 🧪 Dry run again when ready.")
        return {"ok": True, "telegram": command, "cancelled": True}

    if action == "reject" and approval_id:
        try:
            approval = approval_store.reject_request(approval_id, rejected_by=actor, reason="Rejected from Telegram.")
            sync_task_with_approval(approval_id, "rejected", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        message = "Approval request rejected from Telegram."
        return {"ok": True, "telegram": command, "approval": approval, "message": message, "reply": send_telegram_reply(command, message)}

    if action in {"changes", "needs_changes"} and approval_id:
        try:
            approval = approval_store.request_changes(approval_id, requested_by=actor, note="Needs changes requested from Telegram.")
            sync_task_with_approval(approval_id, "needs_changes", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        message = "Approval request marked as needs changes from Telegram."
        return {"ok": True, "telegram": command, "approval": approval, "message": message, "reply": send_telegram_reply(command, message)}

    if action == "menu":
        return _handle_menu(command, approval_id or "menu")

    if action == "cmp":
        return _handle_campaigns(command, callback)

    if action == "kpi":
        return _handle_kpi(command, callback)

    if action == "sug":
        return _handle_suggestions(command, callback)

    if action == "alr":
        return _handle_alerts(command, callback)

    if action == "apv":
        return _handle_pending(command, callback)

    if action == "team":
        return _handle_team(command, callback)

    # Inline Approve/Reject for an agentic free-text proposal (activate / big budget
    # increase / create-test-campaign). callbackData is agap:approve | agap:reject.
    if action == "agap":
        from .. import agentic_chat
        from ..pending_context_store import clear_pending, get_pending, operator_key

        op_key = operator_key(telegram_chat_id=command.get("chatId"))
        pending = get_pending(op_key)
        decision = (approval_id or "").strip().lower()  # callback_target -> approve|reject
        telegram_outbound.edit_message_reply_markup(
            (callback.get("message") or {}).get("chat", {}).get("id"),
            (callback.get("message") or {}).get("message_id"),
            {"inline_keyboard": []},
        )
        if not (pending and pending.get("kind") == "agentic"):
            _send(command, "That proposal is no longer pending.")
            return {"ok": False, "telegram": command, "message": "no agentic pending"}
        if decision == "approve":
            result = agentic_chat.execute_pending(pending, op_key)
            clear_pending(op_key)
            _send(command, result, parse_mode="HTML")
            return {"ok": True, "telegram": command, "agenticApproved": True}
        clear_pending(op_key)
        _send(command, "Cancelled.")
        return {"ok": True, "telegram": command, "agenticRejected": True}

    # Guided campaign creation callbacks (gcreate:aud:* / gcreate:cre:*).
    if action == "gcreate":
        return _handle_guided(command, callback)

    if action == "view" and approval_id:
        approval = next((a for a in list_approval_requests() if a.get("id") == approval_id), None)
        if not approval:
            _send(command, f"Approval not found: {approval_id}")
            return {"ok": False, "telegram": command, "message": "not found"}
        telegram_outbound.send_approval_notification(approval)
        return {"ok": True, "telegram": command, "view": approval_id}

    text = command.get("text") or ""
    if not text:
        _send(command, "Tap /menu for the control panel, or text me a question.")
        return {"ok": False, "telegram": command, "message": "empty"}

    # Persistent reply-keyboard buttons send their label as a normal message.
    reply_button = REPLY_BUTTON_ACTIONS.get(text.strip().lower())
    if reply_button:
        return _handle_menu(command, reply_button)

    lowered = text.strip().lower().lstrip("/")
    if lowered in {"start", "menu"}:
        _send(command, welcome_text(), parse_mode="HTML", reply_markup=main_reply_keyboard())
        return {"ok": True, "telegram": command, "menu": "main"}
    if lowered == "kpis":
        return _open_kpi_panel(command)
    if lowered == "suggestions":
        return _open_suggestions(command)

    # --- Guided campaign: free-text audience answer ----------------------------
    # MUST run before the shortcut/attention handlers: when the operator chose
    # "✍️ I'll specify", the guided flow is parked on the audience_text step and
    # the next free-text message IS the audience description. If its first word
    # happens to be a shortcut keyword ("agents brokers …", "status of …") the
    # shortcut handler would otherwise hijack it and stall the flow.
    from ..pending_context_store import get_pending as _gp_aud, operator_key as _ok_aud

    _aud_opk = _ok_aud(telegram_chat_id=command.get("chatId"))
    _aud_pend = _gp_aud(_aud_opk)
    if (
        _aud_pend
        and _aud_pend.get("kind") == "guided_create"
        and (_aud_pend.get("guided") or {}).get("step") == "audience_text"
    ):
        from .. import guided_campaign

        out = guided_campaign.handle_audience_text(_aud_opk, text)
        _send(command, out["text"], parse_mode="HTML")
        if out.get("next") == "render_creatives":
            return _render_guided_creatives(command, _aud_opk)
        return {"ok": True, "telegram": command, "guided": "audience_text"}

    # Deterministic slash-command shortcuts (/status, /tasks, /approvals, /agents,
    # /help) and the "what needs attention" shortcut stay as-is — they are fast,
    # fixed commands, not the free-text the agentic brain owns.
    shortcut = handle_telegram_shortcut(command, text)
    if shortcut:
        return shortcut
    if is_attention_question(text):
        answer = telegram_attention_text()
        _send(command, answer, parse_mode="HTML")
        return {"ok": True, "shortcut": "attention", "telegram": command, "answer": answer}

    # --- Team add capture (managers only) --------------------------------------
    # When the manager tapped ➕ Add member we stashed a {"kind": "team_add"} pointer;
    # the next free-text message is the new member spec ("@alice admin" / "123 viewer").
    from ..pending_context_store import get_pending as _get_pending, clear_pending as _clear_pending, operator_key as _opkey

    _pend = _get_pending(_opkey(telegram_chat_id=command.get("chatId")))
    if _pend and _pend.get("kind") == "team_add" and access_control.is_manager(role):
        from .. import members_store

        parts = text.split()
        ident, new_role = (parts[0], parts[1].lower()) if len(parts) >= 2 else (text.strip(), "viewer")
        kwargs = {"user_id": ident} if ident.isdigit() else {"username": ident}
        try:
            members_store.add_member(role=new_role, added_by=str(command.get("userId")), **kwargs)
            _clear_pending(_opkey(telegram_chat_id=command.get("chatId")))
            _send(command, f"✅ Added {ident} as {new_role}.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        return {"ok": True, "telegram": command, "team": "added"}

    # --- Viewer free-text block ------------------------------------------------
    # Viewers can browse with reply buttons (handled above) but may not make
    # free-text requests of the agent. Anything that isn't a known reply-button
    # label or a read-only command is refused with the viewer notice.
    if not access_control.is_manager(role) and text.strip().lower() not in REPLY_BUTTON_ACTIONS and lowered not in _VIEWER_FREE_TEXT_ALLOWED:
        _send(command, _VIEWER_NOTICE, parse_mode="HTML", reply_markup=viewer_reply_keyboard())
        return {"ok": False, "telegram": command, "denied": "viewer_chat"}

    # --- Agentic free text -----------------------------------------------------
    # Anything that isn't a reply-keyboard button label, a start/menu command, or a
    # known shortcut goes through the agentic brain (a real Anthropic tool-use loop).
    # It answers questions AND takes actions; reversible/off writes apply directly,
    # spend-increasing ones store a pending agentic proposal the operator approves
    # by text or button.
    from .. import agentic_chat
    from ..pending_context_store import clear_pending, get_pending, operator_key

    op_key = operator_key(telegram_chat_id=command.get("chatId"))

    # The guided audience_text turn is intercepted earlier (before the shortcut
    # handler); here we only need the pending for the agentic affirmation check.
    pending = get_pending(op_key)
    if pending and pending.get("kind") == "agentic":
        from ..routers.agents import _is_affirmation, _is_negation

        if _is_affirmation(text):
            result_text = agentic_chat.execute_pending(pending, op_key)
            clear_pending(op_key)
            _send(command, result_text, parse_mode="HTML")
            return {"ok": True, "telegram": command, "agenticApproved": True}
        if _is_negation(text):
            clear_pending(op_key)
            _send(command, "Cancelled.")
            return {"ok": True, "telegram": command, "agenticRejected": True}

    try:
        answer = asyncio.run(agentic_chat.agentic_reply(text, operator_key=op_key))
    except Exception:
        logger.exception("Telegram agentic chat failed")
        _send(command, "I hit an error answering that. Try again, or tap /menu.")
        return {"ok": False, "telegram": command, "message": "agentic error"}

    # If the create-test-campaign tool opened the GUIDED flow, the model's text
    # answer doesn't carry the audience keyboard — surface the audience question +
    # buttons ourselves and stop (the model's generic answer would just duplicate).
    stashed = get_pending(op_key)
    if stashed and stashed.get("kind") == "guided_create" and (stashed.get("guided") or {}).get("step") == "audience":
        from .. import guided_campaign

        question = guided_campaign.audience_question()
        _send(command, question["text"], parse_mode="HTML", reply_markup=question["reply_markup"])
        return {"ok": True, "telegram": command, "guided": "started"}

    # If the loop stashed a fresh agentic proposal (activate / big budget raise /
    # create-test-campaign autonomous), attach inline Approve/Reject buttons so the
    # operator can tap to approve — typing "approve" works too (handled above).
    reply_markup = None
    if stashed and stashed.get("kind") == "agentic":
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": "agap:approve"},
                {"text": "✖️ Reject", "callback_data": "agap:reject"},
            ]]
        }
    _send(command, clamp_telegram_text(answer), parse_mode="HTML", reply_markup=reply_markup)
    return {"ok": True, "telegram": command, "answer": answer, "agentic": True}


@router.post("/api/telegram/test-message")
def telegram_test_message(request: TelegramTestMessageRequest) -> dict[str, Any]:
    message = request.message.strip() or "Agent approval test"
    return {"ok": True, "telegram": telegram_outbound.send_telegram_message_sync(message)}

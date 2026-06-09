"""Telegram operator routes — button-driven control center + command webhook."""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import approval_store, telegram_outbound
from ..api_models import AgentTaskRequest, TelegramTestMessageRequest
from ..approval_store import list_approval_requests
from ..chat_service import answer_agent_question_sync, to_telegram_html
from ..execution_service import apply_live_sync, auto_execute_paused, dry_run_sync
from ..telegram_commands import normalize_telegram_command
from ..telegram_digest import compose_kpi_digest_text
from ..telegram_menus import (
    REPLY_BUTTON_ACTIONS,
    adset_ads_keyboard,
    approval_adset_detail_keyboard,
    approval_adsets_keyboard,
    approval_stage_keyboard,
    campaign_adsets_keyboard,
    campaigns_list_keyboard,
    main_reply_keyboard,
    pending_approvals_keyboard,
    welcome_text,
)
from ..task_service import create_orchestrated_agent_task, sync_task_with_approval
from ..telegram_service import (
    clamp_telegram_text,
    format_telegram_orchestrator_reply,
    handle_telegram_shortcut,
    is_attention_question,
    send_telegram_reply,
    telegram_attention_text,
    telegram_command_allowed,
    telegram_status_text,
)

# Question-shaped text goes to the conversational brain; action/creation text
# ("create/rename/launch a campaign…") goes to the orchestrator (plans/approvals).
_QUESTION_STARTERS = (
    "what", "why", "how", "which", "should", "is", "are", "can", "do", "does",
    "when", "where", "who", "explain", "tell me", "compare", "summarize", "summarise",
)


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    return t.endswith("?") or t.startswith(_QUESTION_STARTERS)

logger = logging.getLogger(__name__)
router = APIRouter()


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


def _send_pending_suggestions(command: dict[str, Any]) -> str:
    pending = [a for a in list_approval_requests() if a.get("status") == "needs_review"]
    if not pending:
        _send(command, "✅ No suggestions waiting. I'll send new ones here as they come.")
        return "none"
    for approval in pending[:5]:
        telegram_outbound.send_approval_notification(approval)
    return f"{len(pending[:5])} sent"


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


def _approval_total_daily_budget(approval: dict[str, Any]) -> float | None:
    adsets = (approval.get("after") or {}).get("adsets") or []
    total = sum(_to_float(a.get("daily_budget")) / 100 for a in adsets)
    return total or None


def _approval_audience_names(approval: dict[str, Any]) -> list[str]:
    adsets = (approval.get("after") or {}).get("adsets") or []
    return [str(a.get("name", "")).replace(" - DRAFT", "") for a in adsets if a.get("name")]


def _autonomous_created_text(created: list[dict[str, Any]]) -> str:
    """Confirmation message after auto-creating a PAUSED campaign on Telegram."""
    counts: dict[str, int] = {}
    for obj in created or []:
        counts[str(obj.get("level") or "object")] = counts.get(str(obj.get("level") or "object"), 0) + 1
    campaign = next((c for c in (created or []) if c.get("level") == "campaign"), {})
    name = html.escape(str(campaign.get("name", "campaign")))
    parts = []
    for level, label in (("campaign", "campaign"), ("adset", "ad set"), ("ad", "ad")):
        n = counts.get(level, 0)
        if n:
            parts.append(f"{n} {label}" + ("s" if n != 1 else ""))
    summary = ", ".join(parts) or "objects"
    lines = [
        f"✅ Created in Meta as <b>PAUSED</b>: {name}.",
        f"({summary}) — nothing spends until you enable delivery.",
    ]
    if campaign.get("id"):
        lines.append(f"id {html.escape(str(campaign.get('id')))}")
    return "\n".join(lines)


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


# --- Task 4: Pending Approvals drill-down ------------------------------------

def _pending_approvals() -> list[dict[str, Any]]:
    return [a for a in list_approval_requests() if a.get("status") == "needs_review"]


def _pending_list_text(approvals: list[dict[str, Any]]) -> str:
    lines = [f"📝 <b>Pending Approvals</b> ({len(approvals)})"]
    if not approvals:
        lines.append("\n✅ Nothing waiting for review.")
    else:
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
    approvals = _pending_approvals()
    _send(
        command,
        _pending_list_text(approvals),
        parse_mode="HTML",
        reply_markup=pending_approvals_keyboard(approvals),
    )
    return {"ok": True, "telegram": command, "menu": "pending"}


def _handle_pending(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    raw = str(command.get("callbackData") or "")
    tail = raw.split(":", 1)[1] if ":" in raw else ""
    approvals = _pending_approvals()

    if tail == "list":
        _edit(callback, _pending_list_text(approvals), pending_approvals_keyboard(approvals))
        return {"ok": True, "telegram": command, "pending": "list"}

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

    _edit(callback, _pending_list_text(approvals), pending_approvals_keyboard(approvals))
    return {"ok": True, "telegram": command, "pending": "list"}


def _handle_menu(command: dict[str, Any], target: str) -> dict[str, Any]:
    if target == "kpis":
        _send(command, compose_kpi_digest_text(), parse_mode="HTML")
    elif target == "suggestions":
        _send_pending_suggestions(command)
    elif target == "status":
        _send(command, telegram_status_text(), parse_mode="HTML")
    elif target == "alerts":
        _send(command, telegram_attention_text(), parse_mode="HTML")
    elif target == "campaigns":
        return _open_campaigns_list(command)
    elif target == "pending":
        return _open_pending_list(command)
    elif target == "chat":
        _send(command, '💬 Just text me your question — e.g. "what are my best creatives right now?"')
    elif target == "analytics":
        url = os.getenv("PUBLIC_DASHBOARD_URL", "").strip()
        _send(command, f"📊 Open your dashboard: {url}" if url else "Dashboard URL is not configured yet.")
    else:  # "menu" or unknown -> show the main menu
        _send(command, welcome_text(), parse_mode="HTML", reply_markup=main_reply_keyboard())
    return {"ok": True, "telegram": command, "menu": target}


def _reply_conversational(command: dict[str, Any], text: str) -> dict[str, Any]:
    """Route free text to the dashboard brain so texting == web chat.

    Passing the operator key (tg:<chatId>) lets a follow-up answer ("$150/day in
    Tashkent") refine THIS operator's in-flight autonomous draft instead of starting over.
    """
    from ..pending_context_store import operator_key

    op_key = operator_key(telegram_chat_id=command.get("chatId"))
    try:
        result = answer_agent_question_sync(text, operator_key=op_key)
    except Exception:
        logger.exception("Telegram conversational chat failed")
        _send(command, "I hit an error answering that. Try again, or tap /menu.")
        return {"ok": False, "telegram": command, "message": "chat error"}
    _send(command, to_telegram_html(result["answer"]), parse_mode="HTML")
    return {"ok": True, "telegram": command, "answer": result["answer"], "sources": result["sources"]}


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
    if not telegram_command_allowed(command):
        raise HTTPException(status_code=403, detail="Telegram chat or user is not allowed to control this agent.")

    # Acknowledge any button tap immediately so Telegram stops the loading spinner.
    callback = payload.get("callback_query") or {}
    if callback.get("id"):
        telegram_outbound.answer_callback_query(callback.get("id"))

    action = command.get("action")
    approval_id = command.get("approvalId")
    actor = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"

    if action == "approve" and approval_id:
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

    if action == "apv":
        return _handle_pending(command, callback)

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
        _send(command, compose_kpi_digest_text(), parse_mode="HTML")
        return {"ok": True, "telegram": command, "menu": "kpis"}
    if lowered == "suggestions":
        _send_pending_suggestions(command)
        return {"ok": True, "telegram": command, "menu": "suggestions"}

    shortcut = handle_telegram_shortcut(command, text)
    if shortcut:
        return shortcut
    if is_attention_question(text):
        answer = telegram_attention_text()
        _send(command, answer, parse_mode="HTML")
        return {"ok": True, "shortcut": "attention", "telegram": command, "answer": answer}

    # Questions -> conversational brain (control by texting). Other free text
    # (create/rename/launch a campaign, etc.) -> orchestrator (plans/approvals).
    if _looks_like_question(text):
        return _reply_conversational(command, text)

    from ..pending_context_store import clear_pending, get_pending, merge_refinement, operator_key, set_pending

    op_key = operator_key(telegram_chat_id=command.get("chatId"))

    # Pending refinement on the action path too: a non-question follow-up ("$150/day in
    # Tashkent") refines the operator's in-flight autonomous draft instead of starting a
    # fresh task. Delegates to the shared chat brain (which owns the refinement logic).
    pending = get_pending(op_key)
    if pending and pending.get("approvalId") and merge_refinement(pending, text, None):
        return _reply_conversational(command, text)

    source_task = AgentTaskRequest(source="telegram", command=text, operatorKey=op_key)
    result = create_orchestrated_agent_task(source_task)
    task = result.get("task", {})
    plan = task.get("plan") or {}
    answer = plan.get("answer") or "Telegram command sent to the orchestrator."

    # Autonomous build on Telegram: auto-create the PAUSED campaign IMMEDIATELY (operator
    # decision — no separate approval tap), then confirm what was created. Record a pending
    # pointer first so a later answer can still refine the same draft.
    approval = plan.get("generatedApprovalRequest") if isinstance(plan, dict) else None
    if plan.get("autonomous") and isinstance(approval, dict) and approval.get("id"):
        set_pending(
            op_key,
            {
                "approvalId": approval["id"],
                "openQuestions": approval.get("openQuestions") or [],
                "budget": _approval_total_daily_budget(approval),
                "audiences": _approval_audience_names(approval),
                "createdAt": approval.get("createdAt"),
            },
        )
        if approval.get("guardrailResult") != "fail":
            exec_result = auto_execute_paused(approval["id"])
            if exec_result.get("ok"):
                clear_pending(op_key)
                _send(
                    command,
                    clamp_telegram_text(_autonomous_created_text(exec_result.get("created", []))),
                    parse_mode="HTML",
                )
                return {**result, "telegram": command, "autonomousCreated": True, "created": exec_result.get("created", [])}
            blocked = exec_result.get("blocked") or "unknown reason"
            _send(
                command,
                f"I built the PAUSED draft but did not auto-create it in Meta: {html.escape(str(blocked))}. "
                "It is saved for approval.",
                parse_mode="HTML",
            )
            return {**result, "telegram": command, "autonomousCreated": False, "blocked": blocked}

    telegram_reply = send_telegram_reply(command, clamp_telegram_text(format_telegram_orchestrator_reply(plan, answer)))
    return {**result, "telegram": command, "message": "Telegram command sent to the orchestrator.", "reply": telegram_reply}


@router.post("/api/telegram/test-message")
def telegram_test_message(request: TelegramTestMessageRequest) -> dict[str, Any]:
    message = request.message.strip() or "Agent approval test"
    return {"ok": True, "telegram": telegram_outbound.send_telegram_message_sync(message)}

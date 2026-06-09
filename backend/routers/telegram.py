"""Telegram operator routes — button-driven control center + command webhook."""

from __future__ import annotations

import html
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import approval_store, telegram_outbound
from ..api_models import AgentTaskRequest, TelegramTestMessageRequest
from ..approval_store import list_approval_requests
from ..chat_service import answer_agent_question_sync, to_telegram_html
from ..execution_service import apply_live_sync, dry_run_sync
from ..telegram_commands import normalize_telegram_command
from ..telegram_digest import compose_kpi_digest_text
from ..telegram_menus import REPLY_BUTTON_ACTIONS, approval_stage_keyboard, main_reply_keyboard, welcome_text
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


def _handle_menu(command: dict[str, Any], target: str) -> dict[str, Any]:
    if target == "kpis":
        _send(command, compose_kpi_digest_text(), parse_mode="HTML")
    elif target == "suggestions":
        _send_pending_suggestions(command)
    elif target == "status":
        _send(command, telegram_status_text(), parse_mode="HTML")
    elif target == "alerts":
        _send(command, telegram_attention_text(), parse_mode="HTML")
    elif target == "chat":
        _send(command, '💬 Just text me your question — e.g. "what are my best creatives right now?"')
    elif target == "analytics":
        url = os.getenv("PUBLIC_DASHBOARD_URL", "").strip()
        _send(command, f"📊 Open your dashboard: {url}" if url else "Dashboard URL is not configured yet.")
    else:  # "menu" or unknown -> show the main menu
        _send(command, welcome_text(), parse_mode="HTML", reply_markup=main_reply_keyboard())
    return {"ok": True, "telegram": command, "menu": target}


def _reply_conversational(command: dict[str, Any], text: str) -> dict[str, Any]:
    """Route free text to the dashboard brain so texting == web chat."""
    try:
        result = answer_agent_question_sync(text)
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

    source_task = AgentTaskRequest(source="telegram", command=text)
    result = create_orchestrated_agent_task(source_task)
    task = result.get("task", {})
    plan = task.get("plan") or {}
    answer = plan.get("answer") or "Telegram command sent to the orchestrator."
    telegram_reply = send_telegram_reply(command, clamp_telegram_text(format_telegram_orchestrator_reply(plan, answer)))
    return {**result, "telegram": command, "message": "Telegram command sent to the orchestrator.", "reply": telegram_reply}


@router.post("/api/telegram/test-message")
def telegram_test_message(request: TelegramTestMessageRequest) -> dict[str, Any]:
    message = request.message.strip() or "Agent approval test"
    return {"ok": True, "telegram": telegram_outbound.send_telegram_message_sync(message)}

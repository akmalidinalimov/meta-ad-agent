"""Telegram operator command + test-message routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import approval_store, telegram_outbound
from ..api_models import AgentTaskRequest, TelegramTestMessageRequest
from ..telegram_commands import normalize_telegram_command
from ..task_service import create_orchestrated_agent_task, sync_task_with_approval
from ..telegram_service import (
    clamp_telegram_text,
    format_telegram_orchestrator_reply,
    handle_telegram_shortcut,
    is_attention_question,
    send_telegram_reply,
    telegram_attention_text,
    telegram_command_allowed,
)

router = APIRouter()


@router.post("/api/telegram/command")
def telegram_agent_command(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("TELEGRAM_COMMAND_SECRET", "").strip()
    provided_secret = str(
        payload.get("secret")
        or request.headers.get("x-telegram-agent-secret")
        # Telegram's native webhook secret header (setWebhook secret_token),
        # so the bot can post updates here directly without a relay.
        or request.headers.get("x-telegram-bot-api-secret-token")
        or ""
    ).strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid Telegram command secret.")

    command = normalize_telegram_command(payload)
    if not telegram_command_allowed(command):
        raise HTTPException(status_code=403, detail="Telegram chat or user is not allowed to control this agent.")
    if command.get("action") == "approve" and command.get("approvalId"):
        approved_by = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"
        try:
            approval = approval_store.approve_request(command["approvalId"], approved_by=approved_by)
            sync_task_with_approval(command["approvalId"], "approved", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        message = "Approval recorded. Execution still requires the configured execution endpoint."
        telegram_reply = send_telegram_reply(command, message)
        return {
            "ok": True,
            "telegram": command,
            "approval": approval,
            "message": message,
            "reply": telegram_reply,
        }
    if command.get("action") == "reject" and command.get("approvalId"):
        rejected_by = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"
        try:
            approval = approval_store.reject_request(command["approvalId"], rejected_by=rejected_by, reason="Rejected from Telegram.")
            sync_task_with_approval(command["approvalId"], "rejected", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        message = "Approval request rejected from Telegram."
        telegram_reply = send_telegram_reply(command, message)
        return {
            "ok": True,
            "telegram": command,
            "approval": approval,
            "message": message,
            "reply": telegram_reply,
        }
    if command.get("action") in {"changes", "needs_changes"} and command.get("approvalId"):
        requested_by = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"
        try:
            approval = approval_store.request_changes(
                command["approvalId"],
                requested_by=requested_by,
                note="Needs changes requested from Telegram.",
            )
            sync_task_with_approval(command["approvalId"], "needs_changes", approval)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        message = "Approval request marked as needs changes from Telegram."
        telegram_reply = send_telegram_reply(command, message)
        return {
            "ok": True,
            "telegram": command,
            "approval": approval,
            "message": message,
            "reply": telegram_reply,
        }

    text = command.get("text") or ""
    if not text:
        message = "Send a command message, or use callback data like approve:approval_id."
        telegram_reply = send_telegram_reply(command, message)
        return {
            "ok": False,
            "telegram": command,
            "message": message,
            "reply": telegram_reply,
        }

    shortcut = handle_telegram_shortcut(command, text)
    if shortcut:
        return shortcut
    if is_attention_question(text):
        answer = telegram_attention_text()
        reply = send_telegram_reply(command, answer)
        return {
            "ok": True,
            "shortcut": "attention",
            "telegram": command,
            "answer": answer,
            "reply": reply,
        }

    source_task = AgentTaskRequest(source="telegram", command=text)
    result = create_orchestrated_agent_task(source_task)
    task = result.get("task", {})
    plan = task.get("plan") or {}
    answer = plan.get("answer") or "Telegram command sent to the orchestrator."
    telegram_reply = send_telegram_reply(command, clamp_telegram_text(format_telegram_orchestrator_reply(plan, answer)))
    return {
        **result,
        "telegram": command,
        "message": "Telegram command sent to the orchestrator.",
        "reply": telegram_reply,
    }


@router.post("/api/telegram/test-message")
def telegram_test_message(request: TelegramTestMessageRequest) -> dict[str, Any]:
    message = request.message.strip() or "Agent approval test"
    return {"ok": True, "telegram": telegram_outbound.send_telegram_message_sync(message)}

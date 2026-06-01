"""Telegram operator helpers: replies, command permissions, and status text.

Store/alert reads are module-qualified so tests patch them on their source
modules (agent_task_store, approval_store, monitoring_runner, monitoring_scheduler).
"""

from __future__ import annotations

import os
from typing import Any

from . import monitoring_runner, monitoring_scheduler, telegram_outbound
from .agent_task_store import list_agent_tasks
from .approval_store import list_approval_requests
from .agent_orchestrator import agent_registry
from .meta_client import get_meta_config


def send_telegram_reply(command: dict[str, Any], message: str) -> dict[str, Any] | None:
    chat_id = command.get("chatId")
    if not chat_id:
        return None
    return telegram_outbound.send_telegram_message_sync(message, chat_id=chat_id)


def format_telegram_orchestrator_reply(plan: dict[str, Any], answer: str) -> str:
    lines = [answer.strip()]
    active_agent = plan.get("activeAgent")
    if active_agent:
        lines.extend(["", f"Agent: {active_agent}"])
    quality = plan.get("quality") or {}
    if quality:
        lines.append(f"Quality: {quality.get('score', 0)}/100 ({quality.get('status', 'unknown')})")
    decision = plan.get("agentDecision") or {}
    involved = decision.get("involvedAgents") or [
        handoff.get("toAgent")
        for handoff in plan.get("agentHandoffs", [])
        if handoff.get("toAgent")
    ]
    if involved:
        lines.append(f"Involved agents: {', '.join(dict.fromkeys(involved))}")
    suggested = plan.get("suggestedQuestions") or []
    if suggested:
        lines.extend(["", "Next:", *[f"- {item}" for item in suggested[:3]]])
    approval = plan.get("generatedApprovalRequest")
    if approval:
        lines.extend(["", f"Approval: {approval.get('status')} ({approval.get('id')})"])
    lines.append("Safety: no Meta change is published without approval.")
    return "\n".join(lines)


def handle_telegram_shortcut(command: dict[str, Any], text: str) -> dict[str, Any] | None:
    shortcut = text.strip().split(maxsplit=1)[0].lower().lstrip("/")
    handlers = {
        "start": telegram_help_text,
        "help": telegram_help_text,
        "status": telegram_status_text,
        "tasks": telegram_tasks_text,
        "approvals": telegram_approvals_text,
        "agents": telegram_agents_text,
        "attention": telegram_attention_text,
        "monitoring": telegram_attention_text,
    }
    handler = handlers.get(shortcut)
    if not handler:
        return None
    answer = handler()
    reply = send_telegram_reply(command, answer)
    return {
        "ok": True,
        "shortcut": shortcut,
        "telegram": command,
        "answer": answer,
        "reply": reply,
    }


def is_attention_question(text: str) -> bool:
    lower = text.lower()
    return any(
        phrase in lower
        for phrase in [
            "what needs attention",
            "what should i watch",
            "show alerts",
            "monitoring status",
        ]
    )


def telegram_command_allowed(command: dict[str, Any]) -> bool:
    allowed_chat_ids = allowed_telegram_values("TELEGRAM_ALLOWED_CHAT_IDS")
    allowed_user_ids = allowed_telegram_values("TELEGRAM_ALLOWED_USER_IDS")
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if admin_chat_id:
        allowed_chat_ids.add(admin_chat_id)

    if not allowed_chat_ids and not allowed_user_ids:
        return True

    chat_id = str(command.get("chatId") or "").strip()
    user_id = str(command.get("userId") or "").strip()
    return bool((chat_id and chat_id in allowed_chat_ids) or (user_id and user_id in allowed_user_ids))


def allowed_telegram_values(env_name: str) -> set[str]:
    raw = os.getenv(env_name, "")
    return {value.strip() for value in raw.split(",") if value.strip()}


def telegram_help_text() -> str:
    return "\n".join(
        [
            "Meta Agent commands",
            "/status - connection and queue status",
            "/tasks - latest orchestrator tasks",
            "/approvals - pending approval requests",
            "/agents - available specialist agents",
            "/attention - latest monitoring and alert priorities",
            "/help - show this menu",
            "",
            "You can also write a normal instruction, for example: create a paused campaign plan for 3 VSLs.",
        ]
    )


def telegram_status_text() -> str:
    tasks = list_agent_tasks()
    approvals = list_approval_requests()
    connected = "configured" if get_meta_config().ad_account_id else "not configured"
    pending_tasks = len([task for task in tasks if task.get("status") in {"planning", "needs_approval", "needs_changes"}])
    pending_approvals = len([approval for approval in approvals if approval.get("status") == "needs_review"])
    return "\n".join(
        [
            "Agent status",
            f"Meta account: {connected}",
            f"Tasks: {len(tasks)} total, {pending_tasks} pending",
            f"Approvals: {len(approvals)} total, {pending_approvals} waiting for review",
            "Live publish/spend: approval-gated",
        ]
    )


def telegram_tasks_text() -> str:
    tasks = list_agent_tasks()[:5]
    if not tasks:
        return "No agent tasks yet."
    lines = ["Latest tasks"]
    for task in tasks:
        lines.append(f"- {task.get('requestedAction', 'Untitled task')}: {task.get('status')}")
    return "\n".join(lines)


def telegram_attention_text() -> str:
    alerts = monitoring_runner.list_monitoring_alerts()[:5]
    runs = monitoring_scheduler.list_monitoring_runs()[:3]
    lines = ["What needs attention now"]
    if runs:
        latest = runs[0]
        lines.append(
            f"Last monitoring run: {latest.get('status', 'unknown')} at {latest.get('finishedAt') or latest.get('startedAt') or 'unknown'}"
        )
    else:
        lines.append("Last monitoring run: none recorded yet")
    if not alerts:
        lines.append("No saved monitoring alerts. Run /monitoring or the dashboard monitoring check before scaling.")
    else:
        lines.append("Top alerts:")
        for alert in alerts:
            lines.append(f"- {alert.get('severity', 'unknown')}: {alert.get('title', 'Untitled alert')}")
    lines.append("Safety: alerts are recommendations only; execution still requires approval.")
    return "\n".join(lines)


def telegram_approvals_text() -> str:
    approvals = list_approval_requests()[:5]
    if not approvals:
        return "No approval requests yet."
    lines = ["Latest approvals"]
    for approval in approvals:
        campaign_name = approval.get("after", {}).get("campaign", {}).get("name") or approval.get("actionType")
        lines.append(f"- {campaign_name}: {approval.get('status')} ({approval.get('id')})")
    return "\n".join(lines)


def telegram_agents_text() -> str:
    lines = ["Available agents"]
    for agent in agent_registry().values():
        mode = "approval required" if agent.get("requiresApproval") else "analysis ready"
        lines.append(f"- {agent.get('name')}: {mode}")
    return "\n".join(lines)


def clamp_telegram_text(message: str) -> str:
    if len(message) <= 3900:
        return message
    return f"{message[:3890]}\n\n[truncated]"

"""Telegram operator helpers: replies, command permissions, and status text.

Store/alert reads are module-qualified so tests patch them on their source
modules (agent_task_store, approval_store, monitoring_runner, monitoring_scheduler).
"""

from __future__ import annotations

import html
import os
from typing import Any

from . import monitoring_runner, monitoring_scheduler, telegram_outbound
from .agent_task_store import list_agent_tasks
from .approval_store import list_approval_requests
from .agent_orchestrator import agent_registry
from .meta_client import get_meta_config


def _esc(value: Any) -> str:
    """HTML-escape any dynamic value before it lands in an HTML Telegram message."""
    return html.escape(str(value))


def send_telegram_reply(command: dict[str, Any], message: str) -> dict[str, Any] | None:
    chat_id = command.get("chatId")
    if not chat_id:
        return None
    # All operator replies are now structured HTML (bold headers, emoji bullets).
    return telegram_outbound.send_telegram_message_sync(message, chat_id=chat_id, parse_mode="HTML")


def format_telegram_orchestrator_reply(plan: dict[str, Any], answer: str) -> str:
    """Structured HTML reply: the answer, then agent/quality metadata, then any
    decisions, each in its own blank-line-separated section."""
    sections: list[str] = ["<b>🤖 Orchestrator</b>", _esc(answer.strip())]

    # Run metadata (active agent, quality, who was involved) as its own block.
    meta: list[str] = []
    active_agent = plan.get("activeAgent")
    if active_agent:
        meta.append(f"▶️ Agent: <b>{_esc(active_agent)}</b>")
    quality = plan.get("quality") or {}
    if quality:
        score = quality.get("score", 0)
        status = quality.get("status", "unknown")
        marker = "✅" if str(status).lower() in {"pass", "passed", "good", "ok"} else "⚠️"
        meta.append(f"{marker} Quality: {_esc(score)}/100 ({_esc(status)})")
    decision = plan.get("agentDecision") or {}
    involved = decision.get("involvedAgents") or [
        handoff.get("toAgent")
        for handoff in plan.get("agentHandoffs", [])
        if handoff.get("toAgent")
    ]
    if involved:
        names = ", ".join(_esc(name) for name in dict.fromkeys(involved))
        meta.append(f"🤝 Involved agents: {names}")
    if meta:
        sections.append("\n".join(meta))

    # Decisions / approval block.
    decisions: list[str] = []
    approval = plan.get("generatedApprovalRequest")
    if approval:
        decisions.append(f"📝 Approval: {_esc(approval.get('status'))} ({_esc(approval.get('id'))})")
    if decisions:
        sections.append("\n".join(decisions))

    suggested = plan.get("suggestedQuestions") or []
    if suggested:
        followups = "\n".join(f"⏳ {_esc(item)}" for item in suggested[:3])
        sections.append(f"<b>Next:</b>\n{followups}")

    sections.append("🔒 Safety: no Meta change is published without approval.")
    return "\n\n".join(sections)


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
            "<b>📖 Meta Agent commands</b>",
            "Here is everything you can ask me to do.",
            "",
            "/status — connection and queue status",
            "/tasks — latest orchestrator tasks",
            "/approvals — pending approval requests",
            "/agents — available specialist agents",
            "/attention — latest monitoring and alert priorities",
            "/help — show this menu",
            "",
            "You can also write a normal instruction, for example: <i>create a paused campaign plan for 3 VSLs.</i>",
        ]
    )


def telegram_status_text() -> str:
    tasks = list_agent_tasks()
    approvals = list_approval_requests()
    configured = bool(get_meta_config().ad_account_id)
    connected = "configured" if configured else "not configured"
    pending_tasks = len([task for task in tasks if task.get("status") in {"planning", "needs_approval", "needs_changes"}])
    pending_approvals = len([approval for approval in approvals if approval.get("status") == "needs_review"])
    return "\n".join(
        [
            "<b>📈 Agent status</b>",
            f"Everything is running; {pending_tasks} task(s) and {pending_approvals} approval(s) are waiting on you.",
            "",
            f"{'✅' if configured else '⚠️'} Meta account: {_esc(connected)}",
            f"🗒️ Tasks: {len(tasks)} total, {pending_tasks} pending",
            f"📝 Approvals: {len(approvals)} total, {pending_approvals} waiting for review",
            "",
            "🔒 Live publish/spend: approval-gated",
        ]
    )


def telegram_tasks_text() -> str:
    tasks = list_agent_tasks()[:5]
    if not tasks:
        return "<b>🗒️ Latest tasks</b>\nNo agent tasks yet."
    lines = [
        "<b>🗒️ Latest tasks</b>",
        f"Showing your {len(tasks)} most recent task(s).",
        "",
    ]
    for task in tasks:
        status = task.get("status")
        marker = _task_status_emoji(status)
        action = task.get("requestedAction", "Untitled task")
        lines.append(f"{marker} {_esc(action)}: {_esc(status)}")
    return "\n".join(lines)


def _task_status_emoji(status: Any) -> str:
    key = str(status or "").lower()
    if key in {"needs_approval", "needs_changes", "planning"}:
        return "⏳"
    if key in {"approved", "done", "completed"}:
        return "✅"
    if key in {"rejected", "failed", "error"}:
        return "❌"
    return "▶️"


def telegram_attention_text() -> str:
    alerts = monitoring_runner.list_monitoring_alerts()[:5]
    runs = monitoring_scheduler.list_monitoring_runs()[:3]
    lines = [
        "<b>🚨 What needs attention now</b>",
        f"{len(alerts)} alert(s) on the board from the latest monitoring sweep.",
        "",
    ]
    if runs:
        latest = runs[0]
        when = latest.get("finishedAt") or latest.get("startedAt") or "unknown"
        lines.append(f"🕒 Last monitoring run: {_esc(latest.get('status', 'unknown'))} at {_esc(when)}")
    else:
        lines.append("🕒 Last monitoring run: none recorded yet")
    lines.append("")
    if not alerts:
        lines.append("✅ No saved monitoring alerts. Run /monitoring or the dashboard monitoring check before scaling.")
    else:
        lines.append("<b>Top alerts:</b>")
        for alert in alerts:
            marker = _severity_emoji(alert.get("severity"))
            lines.append(f"{marker} {_esc(alert.get('severity', 'unknown'))}: {_esc(alert.get('title', 'Untitled alert'))}")
    lines.append("")
    lines.append("🔒 Safety: alerts are recommendations only; execution still requires approval.")
    return "\n".join(lines)


def _severity_emoji(severity: Any) -> str:
    key = str(severity or "").lower()
    if key in {"high", "critical"}:
        return "❌"
    if key in {"medium", "warning", "warn"}:
        return "⚠️"
    return "ℹ️"


def telegram_approvals_text() -> str:
    approvals = list_approval_requests()[:5]
    if not approvals:
        return "<b>📝 Latest approvals</b>\nNo approval requests yet."
    lines = [
        "<b>📝 Latest approvals</b>",
        f"You have {len(approvals)} approval request(s) to look over.",
        "",
    ]
    for approval in approvals:
        campaign_name = approval.get("after", {}).get("campaign", {}).get("name") or approval.get("actionType")
        status = approval.get("status")
        marker = _approval_status_emoji(status)
        lines.append(f"{marker} {_esc(campaign_name)}: {_esc(status)} ({_esc(approval.get('id'))})")
    return "\n".join(lines)


def _approval_status_emoji(status: Any) -> str:
    key = str(status or "").lower()
    if key in {"approved"}:
        return "✅"
    if key in {"rejected"}:
        return "❌"
    if key in {"needs_review", "needs_changes"}:
        return "⏳"
    return "▶️"


def telegram_agents_text() -> str:
    agents = list(agent_registry().values())
    lines = [
        "<b>🤖 Available agents</b>",
        f"{len(agents)} specialist agent(s) are on call.",
        "",
    ]
    for agent in agents:
        if agent.get("requiresApproval"):
            marker, mode = "⚠️", "approval required"
        else:
            marker, mode = "✅", "analysis ready"
        lines.append(f"{marker} {_esc(agent.get('name'))}: {_esc(mode)}")
    return "\n".join(lines)


def clamp_telegram_text(message: str) -> str:
    if len(message) <= 3900:
        return message
    return f"{message[:3890]}\n\n[truncated]"

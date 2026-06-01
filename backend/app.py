from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .api_models import (
    AgentTaskRequest,
    ApprovalChangesRequest,
    ApprovalDecisionRequest,
    ApprovalExecutionRequest,
    ApprovalRejectRequest,
    CampaignExecutionPlanRequest,
    CampaignPlaybookRequest,
    ChatRequest,
    ChatResponse,
    DraftCampaignProposalRequest,
    FunnelEventRequest,
    ScheduledMonitoringRequest,
    StrategyRequest,
    TelegramTestMessageRequest,
)
from .agent_orchestrator import agent_registry, build_agent_handoffs, orchestrate_agent_chat, route_question
from .agent_quality import evaluate_agent_response
from .agent_task_store import create_agent_task, list_agent_tasks, update_agent_task, update_agent_task_by_approval
from .approval_store import (
    approve_request,
    create_approval_request,
    list_approval_requests,
    reject_request,
    request_changes,
    update_approval_request,
)
from .bitrix_client import HttpBitrixTransport, fetch_bitrix_leads, fetch_bitrix_statuses, get_bitrix_config
from .campaign_watch import build_campaign_watch
from .chatplace_events import normalize_chatplace_event
from .demo_dashboard import (
    ad_sets,
    ads,
    approval_actions,
    audience,
    campaigns,
    creative_analyses,
    creatives,
    experiments,
    glossary,
    insights,
    metrics,
    tracking_health,
)
from .crm_store import STORAGE_DIR as CRM_STORAGE_DIR, list_crm_leads, save_crm_leads
from .routers import funnel as funnel_router
from .routers import meta as meta_router
from .routers import planning as planning_router
from .routers.meta import meta_status
from .dashboard_service import (
    answer_audiences,
    answer_creatives,
    answer_experiments,
    answer_from_knowledge_base,
    answer_funnel,
    answer_meta_status,
    answer_placements,
    answer_summary,
    dashboard_from_knowledge_base,
    default_questions,
    derive_creative_scores,
    derive_funnel,
    derive_kpis,
    derive_placements,
    derive_trend,
    first_playbook_with_segments,
    knowledge_chat_preview,
    map_creative,
    map_metric_row,
)
from .draft_campaign_proposal import build_draft_campaign_proposal
from .funnel_events import build_funnel_summary, save_funnel_event
from .knowledge_base import KNOWLEDGE_BASE_PATH, load_knowledge_base
from .llm_reasoner import generate_chat_answer
from .meta_execution import (
    build_campaign_creation_approval,
    execute_campaign_creation_approval,
    execute_meta_action_approval,
    payload_for_meta_action,
)
from .monitoring_runner import ALERTS_PATH, list_monitoring_alerts, run_monitoring_check
from .monitoring_scheduler import list_monitoring_runs, run_scheduled_monitoring
from .meta_client import (
    create_ad_set as meta_create_ad_set,
    create_campaign as meta_create_campaign,
    get_meta_config,
    update_ad as meta_update_ad,
    update_ad_set as meta_update_ad_set,
    update_campaign as meta_update_campaign,
)
from .playbook_store import load_playbooks, save_playbook
from .strategy_generator import generate_launch_strategy
from .telegram_commands import normalize_telegram_command
from .telegram_outbound import send_approval_notification, send_telegram_message_sync

app = FastAPI(title="Meta Ad Agent API")

DASHBOARD_CACHE: dict[str, Any] = {
    "key": None,
    "payload": None,
}

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FUNNEL_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta_router.router)
app.include_router(planning_router.router)
app.include_router(funnel_router.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/approvals")
def approvals() -> dict[str, Any]:
    return {"approvals": list_approval_requests()}


@app.post("/api/execution/prepare-campaign")
def prepare_campaign_execution(request: CampaignExecutionPlanRequest) -> dict[str, Any]:
    playbook = request.playbook or first_playbook_with_segments(load_playbooks())
    if not playbook:
        raise HTTPException(status_code=400, detail="Save a playbook with at least one segment before preparing execution.")

    account_id = get_meta_config().ad_account_id or "unconfigured_ad_account"
    approval = build_campaign_creation_approval(
        playbook,
        account_id=account_id,
        reason=request.reason or "Prepare a paused Meta campaign structure for review.",
    )
    saved_approval = create_approval_request(approval)
    telegram = send_approval_notification(saved_approval)
    return {"ok": True, "approval": saved_approval, "telegram": telegram}


@app.post("/api/approvals/{approval_id}/approve")
def approve_approval_request(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
    try:
        approval = approve_request(approval_id, approved_by=request.approvedBy)
        task = sync_task_with_approval(approval_id, "approved", approval)
        return {"ok": True, "approval": approval, "task": task}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/approvals/{approval_id}/reject")
def reject_approval_request(approval_id: str, request: ApprovalRejectRequest) -> dict[str, Any]:
    try:
        approval = reject_request(approval_id, rejected_by=request.rejectedBy, reason=request.reason)
        task = sync_task_with_approval(approval_id, "rejected", approval)
        return {
            "ok": True,
            "approval": approval,
            "task": task,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/approvals/{approval_id}/changes")
def request_approval_changes(approval_id: str, request: ApprovalChangesRequest) -> dict[str, Any]:
    try:
        approval = request_changes(approval_id, requested_by=request.requestedBy, note=request.note)
        task = sync_task_with_approval(approval_id, "needs_changes", approval)
        return {
            "ok": True,
            "approval": approval,
            "task": task,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/approvals/{approval_id}/execute")
async def execute_approval_request(approval_id: str, request: ApprovalExecutionRequest) -> dict[str, Any]:
    approval = next((item for item in list_approval_requests() if item.get("id") == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")

    config = get_meta_config()
    if approval.get("actionType") == "create_paused_campaign_structure":
        result = await execute_campaign_creation_approval(
            approval,
            dry_run=request.dryRun,
            confirm_live=request.confirmLive,
            live_writes_enabled=os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true",
            create_campaign=lambda payload: meta_create_campaign(config, payload),
            create_ad_set=lambda payload: meta_create_ad_set(config, payload),
        )
    else:
        result = await execute_meta_action_approval_request(approval, request, config)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("blockedReason") or "Execution failed.")

    status = "dry_run_completed" if request.dryRun else "executed"
    updated = update_approval_request(
        approval_id,
        {
            "status": status,
            "lastExecutionResult": result,
        },
    )
    task_status = "dry_run_completed" if request.dryRun else "executed"
    task = sync_task_with_approval(
        approval_id,
        task_status,
        updated,
        {"executionResult": result},
    )
    return {"ok": True, "approval": updated, "result": result, "task": task}


async def execute_meta_action_approval_request(
    approval: dict[str, Any],
    request: ApprovalExecutionRequest,
    config: Any,
) -> dict[str, Any]:
    if approval.get("status") not in {"approved", "dry_run_completed"}:
        return {"ok": False, "error": "Specific approval is required before execution."}
    if approval.get("guardrailResult") == "fail":
        return {"ok": False, "error": "Guardrail failed; execution is blocked."}

    payload = payload_for_meta_action(approval.get("actionType"), approval.get("after") or {})
    if not payload:
        return {"ok": False, "error": "No executable payload was generated."}

    if request.dryRun:
        return {
            "ok": True,
            "dryRun": True,
            "wouldUpdate": {
                "target": approval.get("target") or {},
                "payload": payload,
            },
            "note": "Dry run only. No request was sent to Meta.",
        }
    if not request.confirmLive:
        return {"ok": False, "dryRun": False, "error": "Final live confirmation is required before Meta writes."}
    if os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() != "true":
        return {"ok": False, "dryRun": False, "error": "Live Meta writes are disabled by configuration."}

    return await execute_meta_action_approval(approval, writer=build_meta_action_writer(config))


def build_meta_action_writer(config: Any) -> Any:
    class MetaActionWriter:
        async def update_campaign(self, object_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            return await meta_update_campaign(config, object_id, payload)

        async def update_ad_set(self, object_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            return await meta_update_ad_set(config, object_id, payload)

        async def update_ad(self, object_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            return await meta_update_ad(config, object_id, payload)

    return MetaActionWriter()


@app.get("/api/agents")
def agents() -> dict[str, Any]:
    live_writes_enabled = os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true"
    return {
        "agents": list(agent_registry().values()),
        "executionEnabled": live_writes_enabled,
        "approvalRequiredForLiveChanges": True,
        "liveWriteScope": "paused_campaign_and_adset_creation_only" if live_writes_enabled else "disabled",
    }


@app.get("/api/crm/bitrix/status")
def bitrix_status() -> dict[str, Any]:
    config = get_bitrix_config()
    return {
        "configured": config.is_configured,
        "message": "Bitrix24 webhook URL configured." if config.is_configured else "Add BITRIX24_WEBHOOK_URL or BITRIX24_PORTAL_URL, BITRIX24_USER_ID, and BITRIX24_WEBHOOK_KEY.",
    }


@app.post("/api/crm/bitrix/import")
async def bitrix_import() -> dict[str, Any]:
    config = get_bitrix_config()
    if not config.is_configured:
        raise HTTPException(status_code=400, detail="Bitrix24 webhook URL is not configured.")
    try:
        leads = await fetch_bitrix_leads(transport=build_bitrix_transport(config))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Bitrix24 import failed: {exc}") from exc
    saved = save_crm_leads(leads, storage_dir=CRM_STORAGE_DIR)
    return {
        "ok": True,
        "imported": len(saved),
        "leads": saved,
    }


@app.get("/api/crm/bitrix/stages")
async def bitrix_stages(entity_id: str = "STATUS") -> dict[str, Any]:
    config = get_bitrix_config()
    if not config.is_configured:
        raise HTTPException(status_code=400, detail="Bitrix24 webhook URL is not configured.")
    try:
        stages = await fetch_bitrix_statuses(transport=build_bitrix_transport(config), entity_id=entity_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Bitrix24 stage discovery failed: {exc}") from exc
    return {
        "ok": True,
        "entityId": entity_id,
        "stages": stages,
    }


@app.get("/api/crm/leads")
def crm_leads() -> dict[str, Any]:
    return {"leads": list_crm_leads(storage_dir=CRM_STORAGE_DIR)}


def build_bitrix_transport(config: Any) -> Any:
    return HttpBitrixTransport(config)


@app.get("/api/tasks")
def agent_tasks() -> dict[str, Any]:
    return {"tasks": list_agent_tasks()}


@app.get("/api/monitoring/alerts")
def monitoring_alerts() -> dict[str, Any]:
    return {"alerts": list_monitoring_alerts()}


@app.post("/api/monitoring/run")
def run_monitoring() -> dict[str, Any]:
    return run_monitoring_check(dashboard(), send_alert=send_telegram_message_sync)


@app.get("/api/monitoring/runs")
def monitoring_runs() -> dict[str, Any]:
    return {"runs": list_monitoring_runs()}


@app.post("/api/monitoring/scheduled")
def scheduled_monitoring(request: ScheduledMonitoringRequest) -> dict[str, Any]:
    return run_scheduled_monitoring(
        dashboard,
        send_alert=send_telegram_message_sync,
        force=request.force,
    )


@app.post("/api/tasks")
def create_orchestrated_agent_task(request: AgentTaskRequest) -> dict[str, Any]:
    command = request.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="Task command is required.")

    task = create_agent_task(
        {
            "source": request.source,
            "command": command,
            "campaignGroupId": request.campaignGroupId,
            "segmentIds": request.segmentIds,
            "status": "planning",
        }
    )
    knowledge = load_knowledge_base()
    orchestrated = orchestrate_agent_chat(command, knowledge=knowledge, playbooks=load_playbooks())
    plan = orchestrated or {
        "activeAgent": "orchestrator",
        "answer": "Task captured. The orchestrator needs more campaign context before it can prepare an execution plan.",
        "sources": ["agent_task_store"],
        "suggestedQuestions": [
            "Which VSL or segment should this task use?",
            "What daily budget should the plan use?",
            "Should this become an approval request?",
        ],
    }

    patch: dict[str, Any] = {
        "status": "planning",
        "activeAgent": plan.get("activeAgent") or "orchestrator",
        "plan": plan,
    }

    generated_playbook = plan.get("generatedPlaybook") if isinstance(plan, dict) else None
    if generated_playbook:
        saved_playbook = save_playbook(generated_playbook)
        plan["generatedPlaybook"] = saved_playbook
        if plan.get("generatedStrategy"):
            plan["generatedStrategy"]["playbookId"] = saved_playbook["id"]

        if request.prepareApproval:
            approval = build_campaign_creation_approval(
                saved_playbook,
                account_id=get_meta_config().ad_account_id or "unconfigured_ad_account",
                reason=f"Task {task['id']}: prepare paused Meta campaign structure from command.",
            )
            saved_approval = create_approval_request(approval)
            plan["telegramNotification"] = send_approval_notification(saved_approval)
            patch["approvalId"] = saved_approval["id"]
            patch["status"] = "needs_approval"

    generated_meta_action_approval = plan.get("generatedApprovalRequest") if isinstance(plan, dict) else None
    if generated_meta_action_approval and generated_meta_action_approval.get("status") == "needs_review":
        saved_approval = create_approval_request(
            {
                **generated_meta_action_approval,
                "reason": f"Task {task['id']}: {generated_meta_action_approval.get('reason', 'natural-language Meta action request')}",
            }
        )
        plan["generatedApprovalRequest"] = saved_approval
        plan["telegramNotification"] = send_approval_notification(saved_approval)
        patch["approvalId"] = saved_approval["id"]
        patch["status"] = "needs_approval"

    updated = update_agent_task(task["id"], patch)
    return {"ok": True, "task": updated}


@app.post("/api/telegram/command")
def telegram_agent_command(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("TELEGRAM_COMMAND_SECRET", "").strip()
    provided_secret = str(payload.get("secret") or request.headers.get("x-telegram-agent-secret") or "").strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid Telegram command secret.")

    command = normalize_telegram_command(payload)
    if not telegram_command_allowed(command):
        raise HTTPException(status_code=403, detail="Telegram chat or user is not allowed to control this agent.")
    if command.get("action") == "approve" and command.get("approvalId"):
        approved_by = f"telegram:{command.get('username') or command.get('userId') or 'unknown'}"
        try:
            approval = approve_request(command["approvalId"], approved_by=approved_by)
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
            approval = reject_request(command["approvalId"], rejected_by=rejected_by, reason="Rejected from Telegram.")
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
            approval = request_changes(
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


@app.post("/api/telegram/test-message")
def telegram_test_message(request: TelegramTestMessageRequest) -> dict[str, Any]:
    message = request.message.strip() or "Agent approval test"
    return {"ok": True, "telegram": send_telegram_message_sync(message)}


def send_telegram_reply(command: dict[str, Any], message: str) -> dict[str, Any] | None:
    chat_id = command.get("chatId")
    if not chat_id:
        return None
    return send_telegram_message_sync(message, chat_id=chat_id)


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
    alerts = list_monitoring_alerts()[:5]
    runs = list_monitoring_runs()[:3]
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


def sync_task_with_approval(
    approval_id: str,
    status: str,
    approval: dict[str, Any],
    extra_patch: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    patch = {
        "status": status,
        "approvalStatus": approval.get("status"),
        "approvalDecision": {
            "status": approval.get("status"),
            "approvedBy": approval.get("approvedBy"),
            "approvedAt": approval.get("approvedAt"),
            "rejectedBy": approval.get("rejectedBy"),
            "rejectedAt": approval.get("rejectedAt"),
            "rejectionReason": approval.get("rejectionReason"),
            "changesRequestedBy": approval.get("changesRequestedBy"),
            "changesRequestedAt": approval.get("changesRequestedAt"),
            "changeRequestNote": approval.get("changeRequestNote"),
        },
    }
    if extra_patch:
        patch.update(extra_patch)
    return update_agent_task_by_approval(approval_id, patch)


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    knowledge = load_knowledge_base()
    if knowledge:
        cache_key = dashboard_cache_key()
        if DASHBOARD_CACHE["key"] == cache_key and DASHBOARD_CACHE["payload"]:
            return DASHBOARD_CACHE["payload"]

        payload = dashboard_from_knowledge_base(knowledge)
        DASHBOARD_CACHE["key"] = cache_key
        DASHBOARD_CACHE["payload"] = payload
        return payload

    return {
        "campaigns": campaigns,
        "adSets": ad_sets,
        "ads": ads,
        "creatives": creatives,
        "creativeAnalyses": creative_analyses,
        "metrics": metrics,
        "kpis": derive_kpis(metrics),
        "funnel": derive_funnel(metrics),
        "trend": derive_trend(metrics),
        "creativeScores": derive_creative_scores(metrics),
        "placements": derive_placements(metrics),
        "audience": audience,
        "insights": insights,
        "experiments": experiments,
        "trackingHealth": tracking_health,
        "monitoringAlerts": list_monitoring_alerts(),
        "campaignWatch": build_campaign_watch(
            {
                "campaigns": campaigns,
                "metrics": metrics,
            }
        ),
        "approvalActions": approval_actions,
        "glossary": glossary,
        "dataSource": {
            "kind": "mock",
            "label": "Mock dashboard model",
            "generatedAt": None,
            "syncErrors": [],
        },
    }


def dashboard_cache_key() -> tuple[int | None, int | None]:
    return (file_mtime_ns(KNOWLEDGE_BASE_PATH), file_mtime_ns(ALERTS_PATH))


def file_mtime_ns(path: Any) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


@app.get("/api/dashboard.js")
def dashboard_script(callback: str = "__META_AD_AGENT_DASHBOARD__") -> Response:
    safe_callback = "".join(character for character in callback if character.isalnum() or character in "._$")
    if not safe_callback:
        safe_callback = "__META_AD_AGENT_DASHBOARD__"
    return Response(
        content=f"{safe_callback}({json.dumps(dashboard(), ensure_ascii=False)});",
        media_type="application/javascript",
    )


def specialist_chat_response(
    question: str,
    *,
    answer: str,
    sources: list[str],
    suggestedQuestions: list[str],
) -> ChatResponse:
    routed = route_question(question)
    payload: dict[str, Any] = {
        "answer": answer,
        "sources": sources,
        "suggestedQuestions": suggestedQuestions,
        "activeAgent": routed["agentId"],
        "routeReason": routed["reason"],
        "agentHandoffs": build_agent_handoffs(routed["agentId"]),
    }
    payload["quality"] = evaluate_agent_response(payload)
    return ChatResponse(**payload)


@app.post("/api/agent/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest) -> ChatResponse:
    question = request.message.strip()
    if not question:
        return ChatResponse(
            answer="Ask me about creatives, audiences, placements, funnel leaks, experiments, or Meta connection status.",
            sources=["agent"],
            suggestedQuestions=default_questions(),
        )

    lower = question.lower()
    dashboard_data = dashboard()
    meta = await meta_status()
    knowledge = load_knowledge_base()
    orchestrated = orchestrate_agent_chat(question, knowledge=knowledge, playbooks=load_playbooks())
    if orchestrated:
        generated_playbook = orchestrated.get("generatedPlaybook")
        if generated_playbook:
            saved_playbook = save_playbook(generated_playbook)
            orchestrated["generatedPlaybook"] = saved_playbook
            if orchestrated.get("generatedStrategy"):
                orchestrated["generatedStrategy"]["playbookId"] = saved_playbook["id"]
            orchestrated["answer"] += "\n\nI saved this as a draft playbook in the dashboard. It is still not executed in Meta Ads."
        return ChatResponse(**orchestrated)

    wants_tracking_answer = any(word in lower for word in ["pixel", "tracking", "visit", "landing", "lead rate", "funnel"])
    wants_connection_status = any(word in lower for word in ["token", "meta api", "account id", "ad account", "api status"])
    if wants_connection_status and not wants_tracking_answer:
        return ChatResponse(
            answer=answer_meta_status(meta),
            sources=["/api/meta/status"],
            suggestedQuestions=[
                "Can you pull my campaigns now?",
                "What Meta data do we still need?",
                "What is the next integration step?",
            ],
        )

    if knowledge:
        try:
            llm_answer = await generate_chat_answer(question, knowledge_chat_preview(knowledge))
        except Exception:
            llm_answer = None
        if llm_answer and not llm_answer.startswith("LLM chat unavailable"):
            return specialist_chat_response(
                question,
                answer=llm_answer,
                sources=["storage/meta_knowledge_base.json", "openai"],
                suggestedQuestions=[
                    "Which audience should we scale?",
                    "How is lead percentage calculated?",
                    "What should we test next?",
                ],
            )
        kb_answer = answer_from_knowledge_base(lower, knowledge)
        if kb_answer:
            return specialist_chat_response(
                question,
                answer=kb_answer,
                sources=["storage/meta_knowledge_base.json"],
                suggestedQuestions=[
                    "Which age and gender should we target?",
                    "Should we target country or region?",
                    "Which placements should we avoid?",
                ],
            )

    if any(word in lower for word in ["connect", "token", "meta", "account", "api"]) and not wants_tracking_answer:
        return ChatResponse(
            answer=answer_meta_status(meta),
            sources=["/api/meta/status"],
            suggestedQuestions=[
                "Can you pull my campaigns now?",
                "What Meta data do we still need?",
                "What is the next integration step?",
            ],
        )

    if any(word in lower for word in ["creative", "video", "hook", "viral", "convert", "conversion"]):
        return ChatResponse(
            answer=answer_creatives(dashboard_data),
            sources=["creativeAnalyses", "metrics"],
            suggestedQuestions=[
                "Which creative should we replicate?",
                "Why did the viral creative not convert?",
                "What creative should we test next?",
            ],
        )

    if any(word in lower for word in ["audience", "age", "buyer", "purchasing", "target"]):
        return ChatResponse(
            answer=answer_audiences(dashboard_data),
            sources=["audience", "metrics"],
            suggestedQuestions=[
                "Which audience should we scale?",
                "Which audience has weak purchasing power?",
                "What targeting should we test next?",
            ],
        )

    if any(word in lower for word in ["placement", "facebook", "instagram", "reels", "feed"]):
        return ChatResponse(
            answer=answer_placements(dashboard_data),
            sources=["placements", "metrics"],
            suggestedQuestions=[
                "Should we turn off Facebook Feed?",
                "Which placement is best for buyers?",
                "How should we split placement budget?",
            ],
        )

    if any(word in lower for word in ["funnel", "telegram", "landing", "webinar", "lead", "leak"]):
        return ChatResponse(
            answer=answer_funnel(dashboard_data),
            sources=["funnel", "trackingHealth"],
            suggestedQuestions=[
                "Where is the biggest funnel leak?",
                "How can we improve Telegram join rate?",
                "Which funnel metric should we watch daily?",
            ],
        )

    if any(word in lower for word in ["experiment", "test", "budget", "scale", "pause", "recommend"]):
        return ChatResponse(
            answer=answer_experiments(dashboard_data),
            sources=["experiments", "approvalActions"],
            suggestedQuestions=[
                "What should we test first?",
                "What should we pause?",
                "What is the safest budget move?",
            ],
        )

    return ChatResponse(
        answer=answer_summary(dashboard_data, meta),
        sources=["dashboard", "/api/meta/status"],
        suggestedQuestions=default_questions(),
    )

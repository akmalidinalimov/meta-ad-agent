"""Orchestrated agent-task creation and approval/task synchronization.

Shared by the tasks router, the telegram router, and the approvals router.
Store access is module-qualified (agent_task_store.x, approval_store.x,
telegram_outbound.x) so tests can patch those source modules once and have every
caller observe the patched, storage-isolated version.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import agent_task_store, approval_store, telegram_outbound
from .agent_task_store import update_agent_task
from .agent_orchestrator import orchestrate_agent_chat
from .api_models import AgentTaskRequest
from .meta_client import get_meta_config
from .meta_execution import build_campaign_creation_approval
from .playbook_store import load_playbooks, save_playbook
from .knowledge_base import load_knowledge_base


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
    return agent_task_store.update_agent_task_by_approval(approval_id, patch)


def create_orchestrated_agent_task(request: AgentTaskRequest) -> dict[str, Any]:
    command = request.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="Task command is required.")

    task = agent_task_store.create_agent_task(
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
            config = get_meta_config()
            approval = build_campaign_creation_approval(
                saved_playbook,
                account_id=config.ad_account_id or "unconfigured_ad_account",
                reason=f"Task {task['id']}: prepare paused Meta campaign structure from command.",
                knowledge=load_knowledge_base(),
                pixel_id=config.pixel_id or None,
            )
            saved_approval = approval_store.create_approval_request(approval)
            plan["telegramNotification"] = telegram_outbound.send_approval_notification(saved_approval)
            patch["approvalId"] = saved_approval["id"]
            patch["status"] = "needs_approval"

    generated_meta_action_approval = plan.get("generatedApprovalRequest") if isinstance(plan, dict) else None
    if generated_meta_action_approval and generated_meta_action_approval.get("status") == "needs_review":
        saved_approval = approval_store.create_approval_request(
            {
                **generated_meta_action_approval,
                "reason": f"Task {task['id']}: {generated_meta_action_approval.get('reason', 'natural-language Meta action request')}",
            }
        )
        plan["generatedApprovalRequest"] = saved_approval
        plan["telegramNotification"] = telegram_outbound.send_approval_notification(saved_approval)
        patch["approvalId"] = saved_approval["id"]
        patch["status"] = "needs_approval"

    updated = update_agent_task(task["id"], patch)
    return {"ok": True, "task": updated}

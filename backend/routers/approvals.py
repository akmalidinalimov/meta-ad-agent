"""Approval queue routes: list, prepare-campaign, approve/reject/changes, execute.

Approval/task store access is module-qualified so tests patch those source
modules; build_meta_action_writer is local to this router (patched here).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import approval_store, telegram_outbound
from ..auth import require_api_key
from ..approval_store import list_approval_requests
from ..api_models import (
    ApprovalChangesRequest,
    ApprovalDecisionRequest,
    ApprovalExecutionRequest,
    ApprovalRejectRequest,
    CampaignExecutionPlanRequest,
)
from ..dashboard_service import first_playbook_with_segments
from ..knowledge_base import load_knowledge_base
from ..meta_client import (
    MetaApiError,
    create_ad as meta_create_ad,
    create_ad_set as meta_create_ad_set,
    create_campaign as meta_create_campaign,
    get_meta_config,
    update_ad as meta_update_ad,
    update_ad_set as meta_update_ad_set,
    update_campaign as meta_update_campaign,
)
from ..config import live_writes_enabled
from ..meta_execution import (
    assert_executable,
    build_campaign_creation_approval,
    execute_campaign_creation_approval,
    execute_meta_action_approval,
    payload_for_meta_action,
)
from ..playbook_store import load_playbooks
from ..task_service import sync_task_with_approval

router = APIRouter()


@router.get("/api/approvals")
def approvals() -> dict[str, Any]:
    return {"approvals": list_approval_requests()}


@router.post("/api/execution/prepare-campaign", dependencies=[Depends(require_api_key)])
def prepare_campaign_execution(request: CampaignExecutionPlanRequest) -> dict[str, Any]:
    playbook = request.playbook or first_playbook_with_segments(load_playbooks())
    if not playbook:
        raise HTTPException(status_code=400, detail="Save a playbook with at least one segment before preparing execution.")

    config = get_meta_config()
    account_id = config.ad_account_id or "unconfigured_ad_account"
    approval = build_campaign_creation_approval(
        playbook,
        account_id=account_id,
        reason=request.reason or "Prepare a paused Meta campaign structure for review.",
        knowledge=load_knowledge_base(),
        pixel_id=config.pixel_id or None,
    )
    saved_approval = approval_store.create_approval_request(approval)
    telegram = telegram_outbound.send_approval_notification(saved_approval)
    return {"ok": True, "approval": saved_approval, "telegram": telegram}


@router.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(require_api_key)])
def approve_approval_request(approval_id: str, request: ApprovalDecisionRequest) -> dict[str, Any]:
    try:
        approval = approval_store.approve_request(approval_id, approved_by=request.approvedBy)
        task = sync_task_with_approval(approval_id, "approved", approval)
        return {"ok": True, "approval": approval, "task": task}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/approvals/{approval_id}/reject", dependencies=[Depends(require_api_key)])
def reject_approval_request(approval_id: str, request: ApprovalRejectRequest) -> dict[str, Any]:
    try:
        approval = approval_store.reject_request(approval_id, rejected_by=request.rejectedBy, reason=request.reason)
        task = sync_task_with_approval(approval_id, "rejected", approval)
        return {
            "ok": True,
            "approval": approval,
            "task": task,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/approvals/{approval_id}/changes", dependencies=[Depends(require_api_key)])
def request_approval_changes(approval_id: str, request: ApprovalChangesRequest) -> dict[str, Any]:
    try:
        approval = approval_store.request_changes(approval_id, requested_by=request.requestedBy, note=request.note)
        task = sync_task_with_approval(approval_id, "needs_changes", approval)
        return {
            "ok": True,
            "approval": approval,
            "task": task,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/approvals/{approval_id}/execute", dependencies=[Depends(require_api_key)])
async def execute_approval_request(approval_id: str, request: ApprovalExecutionRequest) -> dict[str, Any]:
    approval = next((item for item in list_approval_requests() if item.get("id") == approval_id), None)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval request not found: {approval_id}")

    # Idempotency: a retried live execute with the same clientRequestId returns the prior
    # result rather than creating a second campaign / re-applying a change.
    if not request.dryRun and request.clientRequestId:
        for entry in approval.get("executionLog", []):
            if not entry.get("dryRun") and entry.get("clientRequestId") == request.clientRequestId:
                return {"ok": True, "approval": approval, "result": entry.get("result"), "idempotent": True}

    config = get_meta_config()
    try:
        if approval.get("actionType") == "create_paused_campaign_structure":
            result = await execute_campaign_creation_approval(
                approval,
                dry_run=request.dryRun,
                confirm_live=request.confirmLive,
                live_writes_enabled=live_writes_enabled(),
                create_campaign=lambda payload: meta_create_campaign(config, payload),
                create_ad_set=lambda payload: meta_create_ad_set(config, payload),
                create_ad=lambda payload: meta_create_ad(config, payload),
            )
        else:
            result = await execute_meta_action_approval_request(approval, request, config)
    except MetaApiError as error:
        # Surface Meta's actual rejection reason to the operator instead of a 500.
        raise HTTPException(status_code=502, detail=f"Meta API rejected the write: {error}") from error
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("blockedReason") or "Execution failed.")

    status = "dry_run_completed" if request.dryRun else "executed"
    # Append an immutable audit entry (who/when/idempotency key) instead of only
    # overwriting lastExecutionResult, so the money-spending path is auditable.
    execution_log = [
        *approval.get("executionLog", []),
        {
            "executedBy": request.executedBy,
            "executedAt": datetime.now(timezone.utc).isoformat(),
            "clientRequestId": request.clientRequestId,
            "dryRun": request.dryRun,
            "result": result,
        },
    ]
    updated = approval_store.update_approval_request(
        approval_id,
        {
            "status": status,
            "lastExecutionResult": result,
            "executedBy": request.executedBy,
            "executionLog": execution_log,
        },
    )
    task = sync_task_with_approval(
        approval_id,
        status,
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
    # Unified live-write gate (status + guardrail + confirm-live + env flag).
    block = assert_executable(approval, confirm_live=request.confirmLive, live_writes_enabled=live_writes_enabled())
    if block:
        return {"ok": False, "dryRun": False, "error": block}

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

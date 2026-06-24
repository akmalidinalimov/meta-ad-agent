"""Reusable approval execution wrappers for the Telegram apply flow.

Reuses the exact gated path the dashboard uses (routers/approvals.execute_approval_request),
so every safety gate (approved status, guardrail!=fail, confirmLive, live_writes_enabled)
and fixes (e.g. CBO->ABO) apply identically. The sync wrappers run it from the sync
Telegram webhook handler (a threadpool worker, so a fresh event loop is safe). A live
apply carries a deterministic clientRequestId so a double-tap is idempotent (no second
campaign).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _execute(approval_id: str, *, dry_run: bool, confirm_live: bool) -> dict[str, Any]:
    from .api_models import ApprovalExecutionRequest
    from .routers.approvals import execute_approval_request

    request = ApprovalExecutionRequest(
        dryRun=dry_run,
        confirmLive=confirm_live,
        executedBy="telegram",
        # Idempotency key so a repeated Apply-live tap returns the prior result
        # instead of creating a second campaign.
        clientRequestId=None if dry_run else f"telegram-{approval_id}",
    )
    try:
        return await execute_approval_request(approval_id, request)
    except HTTPException as error:
        return {"ok": False, "error": str(error.detail)}


def dry_run_sync(approval_id: str) -> dict[str, Any]:
    return asyncio.run(_execute(approval_id, dry_run=True, confirm_live=False))


def apply_live_sync(approval_id: str) -> dict[str, Any]:
    return asyncio.run(_execute(approval_id, dry_run=False, confirm_live=True))


async def _auto_execute_paused(approval_id: str) -> dict[str, Any]:
    """Approve and execute an autonomously built campaign packet to PAUSED in one step.

    This is the no-tap auto-create path used on both surfaces (web chat + Telegram) once
    the orchestrator has autonomously built a best-guess campaign. Safety conditions, in
    order:

    1. The approval must exist and its ``guardrailResult`` must not be ``"fail"`` — a
       hard-failed guardrail is never auto-executed (it stays needs_review/blocked).
    2. ``live_writes_enabled()`` must be True (the env kill-switch). When disabled we do
       NOT approve or write — we return ``{ok: False, blocked: ...}`` and leave status.
    3. The created objects are PAUSED by construction (the build payloads hardcode status
       PAUSED) and ``assert_executable`` still gates the live write inside
       ``execute_campaign_creation_approval``.

    Returns ``{ok, created: [{level, id, name}], blocked: <reason|None>}``.
    """
    from .config import live_writes_enabled
    from .meta_client import (
        create_ad as meta_create_ad,
        create_ad_set as meta_create_ad_set,
        create_campaign as meta_create_campaign,
        get_meta_config,
    )
    from .meta_execution import execute_campaign_creation_approval
    from . import approval_store

    approval = next(
        (item for item in approval_store.list_approval_requests() if item.get("id") == approval_id),
        None,
    )
    if not approval:
        return {"ok": False, "created": [], "blocked": f"Approval not found: {approval_id}"}
    if approval.get("guardrailResult") == "fail":
        return {"ok": False, "created": [], "blocked": "Guardrail failed; auto-execution is blocked."}
    if not live_writes_enabled():
        return {"ok": False, "created": [], "blocked": "Live Meta writes are disabled by configuration."}

    # Gate passed -> approve, then execute to PAUSED via the shared apply-live path.
    approval = approval_store.approve_request(approval_id, approved_by="agent:autonomous")

    config = get_meta_config()
    try:
        result = await execute_campaign_creation_approval(
            approval,
            dry_run=False,
            confirm_live=True,
            live_writes_enabled=live_writes_enabled(),
            create_campaign=lambda payload: meta_create_campaign(config, payload),
            create_ad_set=lambda payload: meta_create_ad_set(config, payload),
            create_ad=lambda payload: meta_create_ad(config, payload),
        )
    except Exception as error:  # noqa: BLE001 - surface a Meta rejection as a blocked reason, not a 500
        return {"ok": False, "created": [], "blocked": str(error)}

    if not result.get("ok"):
        return {"ok": False, "created": result.get("created", []), "blocked": result.get("error") or "Execution failed."}

    # Persist the executed status + audit entry so the dashboard/Telegram reflect it.
    try:
        execution_log = [
            *approval.get("executionLog", []),
            {
                "executedBy": "agent:autonomous",
                "executedAt": _now_iso(),
                "clientRequestId": f"autonomous-{approval_id}",
                "dryRun": False,
                "result": result,
            },
        ]
        approval_store.update_approval_request(
            approval_id,
            {
                "status": "executed",
                "lastExecutionResult": result,
                "executedBy": "agent:autonomous",
                "executionLog": execution_log,
            },
        )
    except Exception:  # noqa: BLE001 - persistence is best-effort; the write already happened
        pass

    return {"ok": True, "created": result.get("created", []), "blocked": None}


def auto_execute_paused(approval_id: str) -> dict[str, Any]:
    """Sync wrapper for :func:`_auto_execute_paused` (used from sync handlers + tests)."""
    return asyncio.run(_auto_execute_paused(approval_id))

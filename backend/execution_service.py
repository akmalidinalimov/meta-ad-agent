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
from typing import Any

from fastapi import HTTPException


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

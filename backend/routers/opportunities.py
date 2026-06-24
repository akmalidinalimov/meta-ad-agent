"""Proactive opportunity routes (WS-E).

SUGGEST-ONLY. These endpoints generate approval-ready opportunity packets (a
PAUSED test campaign for the top-3 next audiences) and persist them as approvals
the operator can one-tap Approve. Nothing here executes a live Meta change.

Dependencies are imported into this module's namespace so a test can patch them
here (storage dir, loaders, alert sender) without affecting the scheduler's own
call path — same pattern as routers/monitoring.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from ..api_models import GenerateOpportunityRequest, ScheduledOpportunityRequest
from ..auth import require_api_key
from ..knowledge_base import load_knowledge_base
from ..meta_client import get_meta_config
from ..opportunity_finder import generate_opportunity_packets, run_scheduled_opportunities
from ..playbook_store import load_playbooks
from ..telegram_outbound import send_approval_notification

router = APIRouter()


def _account_id() -> str:
    config = get_meta_config()
    return config.ad_account_id or "unconfigured_ad_account"


@router.post("/api/opportunities/scheduled", dependencies=[Depends(require_api_key)])
async def scheduled_opportunities(request: ScheduledOpportunityRequest) -> dict[str, Any]:
    """Debounced daily run for an external cron. SUGGEST-ONLY."""
    return await run_scheduled_opportunities(
        load_knowledge_base,
        load_playbooks=load_playbooks,
        account_id=_account_id(),
        send_alert=send_approval_notification,
        force=request.force,
    )


@router.post("/api/opportunities/generate", dependencies=[Depends(require_api_key)])
async def generate_opportunities(request: GenerateOpportunityRequest) -> dict[str, Any]:
    """Force-generate opportunity packets now (manual/testing), persist them as
    approvals, and notify. SUGGEST-ONLY — every packet stays needs_review."""
    result = await run_scheduled_opportunities(
        load_knowledge_base,
        load_playbooks=load_playbooks,
        account_id=request.accountId or _account_id(),
        per_segment_budget_usd=request.perSegmentBudgetUsd,
        send_alert=send_approval_notification,
        force=True,
    )
    return {
        "ok": result.get("ok", False),
        "approvals": result.get("approvals", []),
        "run": result.get("run"),
    }

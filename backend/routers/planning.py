"""Playbook, strategy, and campaign-proposal (draft) routes.

Read/plan-only: nothing here writes to the approval queue or to Meta.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException

from ..api_models import CampaignPlaybookRequest, DraftCampaignProposalRequest, StrategyRequest
from ..dashboard_service import first_playbook_with_segments
from ..draft_campaign_proposal import build_draft_campaign_proposal
from ..knowledge_base import load_knowledge_base
from ..playbook_store import load_playbooks, save_playbook
from ..strategy_generator import generate_launch_strategy

router = APIRouter()


@router.get("/api/playbooks")
def campaign_playbooks() -> dict[str, Any]:
    return {"playbooks": load_playbooks()}


@router.post("/api/playbooks")
def upsert_campaign_playbook(request: CampaignPlaybookRequest) -> dict[str, Any]:
    return {"playbook": save_playbook(request.playbook)}


@router.post("/api/strategy/generate")
def generate_strategy(request: StrategyRequest) -> dict[str, Any]:
    playbook = request.playbook or load_playbooks()[0]
    knowledge = load_knowledge_base()
    return {
        "ok": True,
        "strategy": generate_launch_strategy(playbook, knowledge),
        "knowledgeAvailable": bool(knowledge),
    }


@router.post("/api/campaign-proposals/draft")
def draft_campaign_proposal(request: DraftCampaignProposalRequest) -> dict[str, Any]:
    playbook = request.playbook or first_playbook_with_segments(load_playbooks())
    if not playbook:
        raise HTTPException(status_code=400, detail="A playbook with at least one segment is required.")
    account_id = request.accountId or os.getenv("META_AD_ACCOUNT_ID") or "act_unconfigured"
    return {
        "ok": True,
        "proposal": build_draft_campaign_proposal(
            playbook,
            load_knowledge_base(),
            account_id=account_id,
        ),
    }

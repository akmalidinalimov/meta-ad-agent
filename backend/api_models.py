"""Pydantic request/response models for the Meta Ad Agent API.

Extracted from app.py so the web layer can be split into routers without each
router re-declaring its schemas. app.py re-exports these names for backward
compatibility (tests and routers import them from either location).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    # Optional operator session id so the web chat can refine its in-flight autonomous
    # draft across turns (maps to a pending_context_store operator key). When absent the
    # shared "web:default" key is used.
    sessionId: str | None = None
    # When True (the default), an autonomously built best-guess campaign is created in
    # Meta as PAUSED immediately (no separate approval tap), per operator decision.
    autoExecute: bool = True


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    suggestedQuestions: list[str]
    activeAgent: str | None = None
    routeReason: str | None = None
    agentHandoffs: list[dict[str, Any]] = Field(default_factory=list)
    agentDecision: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    agentCouncil: dict[str, Any] | None = None
    proactiveInsights: list[dict[str, Any]] | None = None
    generatedPlaybook: dict[str, Any] | None = None
    generatedStrategy: dict[str, Any] | None = None
    generatedMetaActionPlan: dict[str, Any] | None = None
    generatedApprovalRequest: dict[str, Any] | None = None


class MetaSyncRequest(BaseModel):
    days: int = 90


class CampaignPlaybookRequest(BaseModel):
    playbook: dict[str, Any]


class StrategyRequest(BaseModel):
    playbook: dict[str, Any] | None = None


class CampaignExecutionPlanRequest(BaseModel):
    playbook: dict[str, Any] | None = None
    reason: str | None = None


class DraftCampaignProposalRequest(BaseModel):
    playbook: dict[str, Any] | None = None
    accountId: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approvedBy: str = "operator"


class ApprovalRejectRequest(BaseModel):
    rejectedBy: str = "operator"
    reason: str = ""


class ApprovalChangesRequest(BaseModel):
    requestedBy: str = "operator"
    note: str = ""


class ApprovalExecutionRequest(BaseModel):
    dryRun: bool = True
    confirmLive: bool = False
    executedBy: str = "operator"
    # Optional client-supplied idempotency key: a retried/double-clicked live execute
    # with the same key returns the prior result instead of creating a second campaign.
    clientRequestId: str | None = None


class ScheduledMonitoringRequest(BaseModel):
    force: bool = False


class ScheduledOpportunityRequest(BaseModel):
    # External cron hits the debounced endpoint with force=False; manual/testing
    # callers pass force=True to bypass the 24h cooldown.
    force: bool = False


class GenerateOpportunityRequest(BaseModel):
    # Force-generate now (manual/testing). Optional overrides degrade to defaults.
    accountId: str | None = None
    perSegmentBudgetUsd: float | None = None


class FunnelEventRequest(BaseModel):
    event: dict[str, Any]


class TelegramTestMessageRequest(BaseModel):
    message: str = "Agent approval test"


class AgentTaskRequest(BaseModel):
    source: str = "dashboard"
    command: str
    campaignGroupId: str | None = None
    segmentIds: list[str] = []
    prepareApproval: bool = False
    # Optional operator key (e.g. "tg:12345") so a Telegram-originated task can refine
    # its in-flight autonomous draft across turns. None keeps the prior behavior.
    operatorKey: str | None = None


class CouncilRequest(BaseModel):
    message: str


class MetaAiCaptureRequest(BaseModel):
    sourceText: str = ""
    screenshotText: str = ""
    campaignId: str | None = None
    campaignName: str | None = None
    objectLevel: str | None = None
    capturedBy: str = "operator"

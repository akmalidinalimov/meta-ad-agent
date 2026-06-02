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


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    suggestedQuestions: list[str]
    activeAgent: str | None = None
    routeReason: str | None = None
    agentHandoffs: list[dict[str, Any]] = Field(default_factory=list)
    agentDecision: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
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
    approvedBy: str = "akmal"


class ApprovalRejectRequest(BaseModel):
    rejectedBy: str = "akmal"
    reason: str = ""


class ApprovalChangesRequest(BaseModel):
    requestedBy: str = "akmal"
    note: str = ""


class ApprovalExecutionRequest(BaseModel):
    dryRun: bool = True
    confirmLive: bool = False


class ScheduledMonitoringRequest(BaseModel):
    force: bool = False


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


class MetaAiCaptureRequest(BaseModel):
    sourceText: str = ""
    screenshotText: str = ""
    campaignId: str | None = None
    campaignName: str | None = None
    objectLevel: str | None = None
    capturedBy: str = "operator"

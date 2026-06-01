"""Agent task routes: list tasks and create an orchestrated task."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..agent_task_store import list_agent_tasks
from ..api_models import AgentTaskRequest
from ..task_service import create_orchestrated_agent_task

router = APIRouter()


@router.get("/api/tasks")
def agent_tasks() -> dict[str, Any]:
    return {"tasks": list_agent_tasks()}


@router.post("/api/tasks")
def create_agent_task_route(request: AgentTaskRequest) -> dict[str, Any]:
    return create_orchestrated_agent_task(request)

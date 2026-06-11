"""Read-only status feed for the dashboard's Agent Office."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from .. import agent_activity
from ..monitoring_scheduler import list_monitoring_runs, parse_datetime

router = APIRouter()


def _next_run(runs: list[dict[str, Any]], interval_hours: int) -> str | None:
    """Most recent completed run + interval = the next scheduled run."""
    for run in runs:
        if run.get("status") == "completed" and run.get("finishedAt"):
            finished = parse_datetime(str(run["finishedAt"]))
            if finished:
                # parse_datetime already ensures UTC-aware, but be safe
                if finished.tzinfo is None:
                    finished = finished.replace(tzinfo=timezone.utc)
                return (finished + timedelta(hours=interval_hours)).isoformat()
    return None


@router.get("/api/agents/status")
def agents_status() -> dict[str, Any]:
    from ..opportunity_finder import list_opportunity_runs

    live = agent_activity.live_state()
    stored = agent_activity.stored()
    last_active = stored["lastActive"]
    now = datetime.now(timezone.utc)

    next_runs: dict[str, str | None] = {
        "monitor": _next_run(list_monitoring_runs(), 4),
        "planner": _next_run(list_opportunity_runs(), 24),
    }

    agents: list[dict[str, Any]] = []
    for agent_id, name in agent_activity.AGENTS.items():
        last = last_active.get(agent_id) or {}
        entry = live.get(agent_id)
        if entry:
            started = parse_datetime(str(entry.get("startedAt") or ""))
            if started and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            since = int((now - started).total_seconds()) if started else None
            agents.append(
                {
                    "id": agent_id,
                    "name": name,
                    "state": "working",
                    "activity": entry.get("activity"),
                    "sinceSeconds": max(since, 0) if since is not None else None,
                    "nextRunAt": None,
                    "lastActivity": last.get("summary"),
                    "lastActiveAt": last.get("at"),
                }
            )
            continue
        next_run = next_runs.get(agent_id)
        agents.append(
            {
                "id": agent_id,
                "name": name,
                "state": "scheduled" if next_run else "idle",
                "activity": None,
                "sinceSeconds": None,
                "nextRunAt": next_run,
                "lastActivity": last.get("summary"),
                "lastActiveAt": last.get("at"),
            }
        )

    return {"agents": agents, "events": stored["events"][:20], "updatedAt": now.isoformat()}

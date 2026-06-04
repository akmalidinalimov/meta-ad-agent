from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, update_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"


def _path(storage_dir: Path) -> Path:
    return storage_dir / "agent_tasks.json"


def list_agent_tasks(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    payload = read_json(_path(storage_dir), [])
    return payload if isinstance(payload, list) else []


def create_agent_task(task: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    saved = {
        "id": task.get("id") or f"task_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "source": task.get("source") or "dashboard",
        "status": task.get("status") or "draft",
        "requestedAction": task.get("requestedAction") or task.get("command") or "",
        "campaignGroupId": task.get("campaignGroupId"),
        "segmentIds": task.get("segmentIds") or [],
        "activeAgent": task.get("activeAgent") or "orchestrator",
        "plan": task.get("plan"),
        "approvalId": task.get("approvalId"),
        "executionResult": task.get("executionResult"),
        "createdAt": task.get("createdAt") or now,
        "updatedAt": now,
        "history": task.get("history") or [{"status": task.get("status") or "draft", "at": now}],
    }

    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rows.insert(0, saved)
        return saved

    return update_json(_path(storage_dir), mutate, default=[])


def update_agent_task(task_id: str, patch: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if row.get("id") == task_id:
                row.update(patch)
                row["updatedAt"] = now
                row.setdefault("history", []).append({"status": row.get("status", "updated"), "at": now})
                return row
        raise KeyError(f"Agent task not found: {task_id}")

    return update_json(_path(storage_dir), mutate, default=[])


def update_agent_task_by_approval(
    approval_id: str,
    patch: dict[str, Any],
    *,
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any] | None:
    rows = list_agent_tasks(storage_dir=storage_dir)
    for row in rows:
        if row.get("approvalId") == approval_id:
            return update_agent_task(str(row["id"]), patch, storage_dir=storage_dir)
    return None


def write_agent_tasks(rows: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> None:
    write_json_atomic(_path(storage_dir), rows)

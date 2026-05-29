from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"


def list_agent_tasks(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "agent_tasks.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def create_agent_task(task: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    rows = list_agent_tasks(storage_dir=storage_dir)
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
    rows.insert(0, saved)
    write_agent_tasks(rows, storage_dir=storage_dir)
    return saved


def update_agent_task(task_id: str, patch: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    rows = list_agent_tasks(storage_dir=storage_dir)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("id") == task_id:
            row.update(patch)
            row["updatedAt"] = now
            row.setdefault("history", []).append({
                "status": row.get("status", "updated"),
                "at": now,
            })
            write_agent_tasks(rows, storage_dir=storage_dir)
            return row
    raise KeyError(f"Agent task not found: {task_id}")


def write_agent_tasks(rows: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "agent_tasks.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

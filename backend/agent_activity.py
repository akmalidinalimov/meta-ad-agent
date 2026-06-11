"""Agent activity registry for the dashboard's Agent Office.

Live "working" state is held in-process — it reflects *right now*, so losing it
on restart is correct. Completed work persists to storage/agent_activity.json
(a capped event feed plus per-agent last-active stamps) so the office still
shows recent history after a service restart.

Real jobs call begin()/end() around real work; the dashboard reads the
snapshot. An agent never shows "working" unless something is genuinely running.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, update_json

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
EVENTS_FILE = "agent_activity.json"
MAX_EVENTS = 50

AGENTS: dict[str, str] = {
    "monitor": "Monitor",
    "analyst": "Analyst",
    "planner": "Planner",
    "creative": "Creative",
}

_live: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(storage_dir: Path) -> Path:
    return storage_dir / EVENTS_FILE


def begin(agent_id: str, activity: str) -> None:
    """Mark an agent as working on `activity`. Unknown ids are ignored."""
    if agent_id not in AGENTS:
        return
    with _lock:
        _live[agent_id] = {"activity": activity, "startedAt": _now_iso()}


def end(agent_id: str, summary: str | None = None, *, storage_dir: Path = STORAGE_DIR) -> None:
    """Mark an agent as done. With a summary, persist a feed event and the
    last-active stamp; without one (skipped or failed runs) just clear the
    live state so nothing false lands in the feed."""
    if agent_id not in AGENTS:
        return
    with _lock:
        live = _live.pop(agent_id, None)
    if not summary:
        return
    at = _now_iso()
    activity = (live or {}).get("activity") or summary

    def mutate(data: dict[str, Any]) -> None:
        events = data.setdefault("events", [])
        events.insert(0, {"agentId": agent_id, "summary": summary, "at": at})
        del events[MAX_EVENTS:]
        data.setdefault("lastActive", {})[agent_id] = {
            "activity": activity,
            "summary": summary,
            "at": at,
        }

    update_json(_path(storage_dir), mutate, default={"events": [], "lastActive": {}})


def live_state() -> dict[str, dict[str, Any]]:
    with _lock:
        return {key: dict(value) for key, value in _live.items()}


def stored(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    payload = read_json(_path(storage_dir), None)
    if not isinstance(payload, dict):
        return {"events": [], "lastActive": {}}
    events = payload.get("events")
    last = payload.get("lastActive")
    return {
        "events": events if isinstance(events, list) else [],
        "lastActive": last if isinstance(last, dict) else {},
    }


def reset_live_for_tests() -> None:
    with _lock:
        _live.clear()

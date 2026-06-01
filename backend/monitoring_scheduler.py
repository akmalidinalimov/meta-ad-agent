from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .monitoring_runner import AlertSender, STORAGE_DIR, run_monitoring_check

DashboardFactory = Callable[[], dict[str, Any]]
RUNS_PATH = STORAGE_DIR / "monitoring_runs.json"


def run_scheduled_monitoring(
    dashboard_factory: DashboardFactory,
    *,
    storage_dir: Path = STORAGE_DIR,
    send_alert: AlertSender | None = None,
    interval_hours: int = 4,
    force: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    previous_runs = list_monitoring_runs(storage_dir=storage_dir)
    last_completed = first_completed_run(previous_runs)

    if not force and last_completed and within_interval(last_completed, now, interval_hours):
        run = {
            "id": run_id(now),
            "status": "skipped",
            "mode": "alert_only",
            "startedAt": now.isoformat(),
            "finishedAt": now.isoformat(),
            "reason": f"Monitoring already ran within the last {interval_hours} hours.",
            "alertsCreated": 0,
            "snapshotsChecked": 0,
        }
        save_monitoring_run(run, storage_dir=storage_dir)
        return {"ok": True, "skipped": True, "mode": "alert_only", "run": run}

    run = {
        "id": run_id(now),
        "status": "running",
        "mode": "alert_only",
        "startedAt": now.isoformat(),
        "intervalHours": interval_hours,
    }
    try:
        result = run_monitoring_check(
            dashboard_factory(),
            storage_dir=storage_dir,
            send_alert=send_alert,
        )
        finished = datetime.now(timezone.utc)
        run.update(
            {
                "status": "completed",
                "finishedAt": finished.isoformat(),
                "alertsCreated": len(result.get("alerts", [])),
                "snapshotsChecked": result.get("snapshotsChecked", 0),
                "notificationsSent": len(result.get("notifications", [])),
                "executionAllowed": False,
            }
        )
        save_monitoring_run(run, storage_dir=storage_dir)
        return {"ok": True, "skipped": False, "mode": "alert_only", "run": run, "result": result}
    except Exception as exc:
        finished = datetime.now(timezone.utc)
        run.update(
            {
                "status": "failed",
                "finishedAt": finished.isoformat(),
                "error": str(exc),
                "executionAllowed": False,
            }
        )
        save_monitoring_run(run, storage_dir=storage_dir)
        return {"ok": False, "skipped": False, "mode": "alert_only", "run": run, "error": str(exc)}


def list_monitoring_runs(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "monitoring_runs.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def save_monitoring_run(run: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> None:
    rows = [run, *list_monitoring_runs(storage_dir=storage_dir)]
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "monitoring_runs.json").write_text(
        json.dumps(rows[:100], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def first_completed_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((run for run in runs if run.get("status") == "completed"), None)


def within_interval(run: dict[str, Any], now: datetime, interval_hours: int) -> bool:
    finished = parse_datetime(str(run.get("finishedAt") or run.get("startedAt") or ""))
    return finished is not None and now - finished < timedelta(hours=interval_hours)


def parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def run_id(now: datetime) -> str:
    return f"monitoring_run_{now.strftime('%Y%m%dT%H%M%SZ')}"

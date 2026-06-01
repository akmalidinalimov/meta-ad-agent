"""Campaign monitoring routes (manual run, scheduled run, alert/run logs).

Dependencies are imported into this module's namespace so a test can patch
them here without affecting the scheduler's own internal monitoring call.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..api_models import ScheduledMonitoringRequest
from ..dashboard_service import build_dashboard
from ..monitoring_runner import list_monitoring_alerts, run_monitoring_check
from ..monitoring_scheduler import list_monitoring_runs, run_scheduled_monitoring
from ..telegram_outbound import send_telegram_message_sync

router = APIRouter()


@router.get("/api/monitoring/alerts")
def monitoring_alerts() -> dict[str, Any]:
    return {"alerts": list_monitoring_alerts()}


@router.post("/api/monitoring/run")
def run_monitoring() -> dict[str, Any]:
    return run_monitoring_check(build_dashboard(), send_alert=send_telegram_message_sync)


@router.get("/api/monitoring/runs")
def monitoring_runs() -> dict[str, Any]:
    return {"runs": list_monitoring_runs()}


@router.post("/api/monitoring/scheduled")
def scheduled_monitoring(request: ScheduledMonitoringRequest) -> dict[str, Any]:
    return run_scheduled_monitoring(
        build_dashboard,
        send_alert=send_telegram_message_sync,
        force=request.force,
    )

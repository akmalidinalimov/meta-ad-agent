"""Daily Funnel Analyst trigger + read endpoints.

POST /api/analysis/daily  — forces a run+send (manual button / external cron).
GET  /api/analysis/daily  — returns the latest analysis object for the dashboard
                            without sending a Telegram message.

Auth posture: same as /api/monitoring/scheduled — not in _AUTH_PUBLIC_PATHS, so
it requires a dashboard session when DASHBOARD_SESSION_AUTH=true (production), but
is freely reachable in tests/dev (auth disabled by default).
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from ..daily_analysis_scheduler import run_scheduled_daily_analysis
from ..daily_analyst import run_daily_analysis

router = APIRouter()


@router.post("/api/analysis/daily")
async def trigger_daily_analysis() -> dict[str, Any]:
    """Force the daily analyst to run and send the Telegram report now."""
    return await asyncio.to_thread(run_scheduled_daily_analysis, force=True)


@router.get("/api/analysis/daily")
async def get_daily_analysis() -> dict[str, Any]:
    """Return the latest daily analysis object (no Telegram send)."""
    return await run_daily_analysis()

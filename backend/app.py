"""Meta Ad Agent API entrypoint.

This module is the composition root: it builds the FastAPI app, configures CORS,
and mounts the domain routers from backend/routers/. Endpoint logic lives in the
routers and the service modules they depend on.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import allowed_origins
from .routers import agents as agents_router
from .routers import approvals as approvals_router
from .routers import crm as crm_router
from .routers import dashboard as dashboard_router
from .routers import funnel as funnel_router
from .routers import meta as meta_router
from .routers import meta_ai as meta_ai_router
from .routers import monitoring as monitoring_router
from .routers import planning as planning_router
from .routers import tasks as tasks_router
from .routers import telegram as telegram_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)


async def _monitoring_loop() -> None:
    """In-process monitoring trigger.

    The monitoring rules only fire when something invokes run_scheduled_monitoring;
    by default nothing did, so the '4-hourly check' was dormant. This optional loop
    drives it. It is OFF by default (MONITORING_SCHEDULER_ENABLED) — in production an
    external cron POSTing /api/monitoring/scheduled is preferred (safer with the
    file-based stores). run_scheduled_monitoring keeps its own 4h debounce, so the
    poll interval here only sets how often we check.
    """
    from .dashboard_service import build_dashboard
    from .monitoring_scheduler import run_scheduled_monitoring
    from .telegram_outbound import send_telegram_message_sync

    interval = int(os.getenv("MONITORING_INTERVAL_SECONDS", "3600"))
    while True:
        try:
            await asyncio.to_thread(
                run_scheduled_monitoring,
                build_dashboard,
                send_alert=send_telegram_message_sync,
            )
        except Exception:
            logger.exception("Scheduled monitoring iteration failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task: asyncio.Task | None = None
    if os.getenv("MONITORING_SCHEDULER_ENABLED", "").strip().lower() == "true":
        logger.info("Starting in-process monitoring scheduler")
        task = asyncio.create_task(_monitoring_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title="Meta Ad Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    meta_router,
    planning_router,
    funnel_router,
    crm_router,
    dashboard_router,
    monitoring_router,
    approvals_router,
    tasks_router,
    telegram_router,
    meta_ai_router,
    agents_router,
):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import mcp_server
from .config import allowed_origins
from .routers import agents as agents_router
from .routers import auth as auth_router
from .routers import approvals as approvals_router
from .routers import campaigns as campaigns_router
from .routers import crm as crm_router
from .routers import dashboard as dashboard_router
from .routers import funnel as funnel_router
from .routers import members as members_router
from .routers import agent_status as agent_status_router
from .routers import meta as meta_router
from .routers import meta_ai as meta_ai_router
from .routers import monitoring as monitoring_router
from .routers import opportunities as opportunities_router
from .routers import planning as planning_router
from .routers import targets as targets_router
from .routers import tasks as tasks_router
from .routers import telegram as telegram_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

# httpx logs every request line at INFO, including the full URL — and Meta Graph
# calls carry ?access_token=... in the query string, so INFO logs would leak the
# long-lived token to the platform's log stream once deployed. Quiet the HTTP
# client loggers so tokens never reach logs; our own logging carries no secrets.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


async def _monitoring_loop() -> None:
    """In-process monitoring trigger.

    The monitoring rules only fire when something invokes run_scheduled_monitoring;
    by default nothing did, so the '4-hourly check' was dormant. This optional loop
    drives it. It is OFF by default (MONITORING_SCHEDULER_ENABLED) — in production an
    external cron POSTing /api/monitoring/scheduled is preferred (safer with the
    file-based stores). run_scheduled_monitoring keeps its own 4h debounce, so the
    poll interval here only sets how often we check.

    The same loop also drives the PROACTIVE opportunity engine (WS-E). Monitoring
    alerts keep their 4h cadence; opportunities run daily — each function keeps its
    own debounce (monitoring 4h, opportunities 24h), so the shared poll interval
    only sets how often both are checked. The opportunity engine is SUGGEST-ONLY:
    it never executes a Meta change, it only creates needs_review approvals.
    """
    from .dashboard_service import build_dashboard
    from .knowledge_base import load_knowledge_base
    from .meta_client import get_meta_config
    from .monitoring_scheduler import run_scheduled_monitoring
    from .opportunity_finder import run_scheduled_opportunities
    from .playbook_store import load_playbooks
    from .telegram_outbound import send_approval_notification, send_telegram_message_sync

    from .telegram_digest import send_kpi_digest
    from .agent_activity import begin as agent_begin, end as agent_end

    interval = int(os.getenv("MONITORING_INTERVAL_SECONDS", "3600"))
    while True:
        try:
            agent_begin("monitor", "scanning campaigns and ad sets")
            monitoring_result = await asyncio.to_thread(
                run_scheduled_monitoring,
                build_dashboard,
                send_alert=send_telegram_message_sync,
            )
            # Heartbeat: when monitoring actually runs (its own 4h debounce, not a
            # skipped poll), push the KPI digest so the operator always gets a
            # status table — not only when a rule trips. Read-only, no Meta writes.
            ran = isinstance(monitoring_result, dict) and not monitoring_result.get("skipped")
            agent_end("monitor", "monitoring scan completed" if ran else None)
            if ran:
                agent_begin("analyst", "sending KPI digest to Telegram")
                await asyncio.to_thread(send_kpi_digest)
                agent_end("analyst", "KPI digest sent to Telegram")
        except Exception:
            agent_end("monitor")
            agent_end("analyst")
            logger.exception("Scheduled monitoring iteration failed")
        try:
            agent_begin("planner", "daily opportunity review")
            config = get_meta_config()
            opportunity_result = await run_scheduled_opportunities(
                load_knowledge_base,
                load_playbooks=load_playbooks,
                account_id=config.ad_account_id or "unconfigured_ad_account",
                send_alert=send_approval_notification,
            )
            ran = isinstance(opportunity_result, dict) and not opportunity_result.get("skipped")
            agent_end("planner", "opportunity review completed" if ran else None)
        except Exception:
            agent_end("planner")
            logger.exception("Scheduled opportunity iteration failed")
        await asyncio.sleep(interval)


# Streamable-HTTP MCP connector. Only built/mounted when MCP_PATH_SECRET is set
# (the secret path is the auth boundary). The FastMCP app carries its own session
# manager whose lifespan MUST run or the endpoint 500s, so it is folded into the
# app lifespan below.
_mcp_path = mcp_server.mount_path()
_mcp_app = mcp_server.streamable_app() if _mcp_path else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    task: asyncio.Task | None = None
    if os.getenv("MONITORING_SCHEDULER_ENABLED", "").strip().lower() == "true":
        logger.info("Starting in-process monitoring scheduler")
        task = asyncio.create_task(_monitoring_loop())
    # Register the Telegram command menu + menu button so the bot is button-driven.
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_AUTO_SETUP", "true").strip().lower() != "false":
        try:
            from .telegram_setup import register_bot_ui

            await asyncio.to_thread(register_bot_ui)
            logger.info("Registered Telegram bot menu + commands")
        except Exception:
            logger.exception("Telegram bot UI registration failed")
    try:
        # Run the FastMCP session-manager lifespan alongside the app's startup so
        # the mounted Streamable-HTTP endpoint works (it 500s without it).
        if _mcp_app is not None:
            logger.info("Mounting MCP connector at %s", _mcp_path)
            async with _mcp_app.router.lifespan_context(_mcp_app):
                yield
        else:
            yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title="Meta Ad Agent API", lifespan=lifespan)

# Mount the MCP connector before the SPA catch-all route is registered, so its
# secret path wins over the client-side route fallback.
if _mcp_app is not None:
    app.mount(_mcp_path, _mcp_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths reachable without a dashboard session: health, the auth endpoints, and the
# Telegram webhook (which carries its own secret). The SPA shell + /assets are served
# below and are intentionally public (they hold no account data).
_AUTH_PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/session",
    "/api/telegram/webapp-auth",
    "/api/telegram/command",
    # ChatPlace bot webhook — authenticated by CHATPLACE_WEBHOOK_SECRET
    # (x-chatplace-secret header / `secret` body field), not a dashboard session.
    "/api/chatplace/events",
    # Landing-page funnel beacon — posted from end-user browsers, so it cannot
    # carry a dashboard session. It only appends anonymous funnel analytics events.
    "/api/funnel/events",
}


@app.middleware("http")
async def _session_guard(request: Request, call_next):
    """Gate dashboard data endpoints on a valid session — only when
    DASHBOARD_SESSION_AUTH=true (off in tests/dev, on in production behind no Caddy
    password)."""
    from .access_control import can
    from .webapp_auth import COOKIE_NAME, dashboard_auth_enabled, session_role, valid_session

    # The MCP connector is gated by its own secret mount path, not the dashboard
    # session — never apply the session guard to it.
    if request.url.path.startswith("/mcp/"):
        return await call_next(request)

    if dashboard_auth_enabled():
        path = request.url.path
        if path.startswith("/api/") and path not in _AUTH_PUBLIC_PATHS:
            token = request.cookies.get(COOKIE_NAME)
            if not valid_session(token):
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            # Viewers (and any non-act role) may read but never mutate.
            if request.method not in ("GET", "HEAD", "OPTIONS") and not can(session_role(token), "act"):
                return JSONResponse({"detail": "Read-only access."}, status_code=403)
    return await call_next(request)


for module in (
    meta_router,
    auth_router,
    planning_router,
    funnel_router,
    crm_router,
    campaigns_router,
    dashboard_router,
    monitoring_router,
    opportunities_router,
    approvals_router,
    tasks_router,
    targets_router,
    telegram_router,
    meta_ai_router,
    agents_router,
    members_router,
    agent_status_router,
):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Single-process deployment: serve the built SPA same-origin ---------------
#
# When the Vite build (dist/) is present, FastAPI also serves the frontend so the
# whole app ships as ONE unit with no CORS / base-URL juggling — apiUrl() in the
# frontend already returns relative /api/... off-localhost. The mount is guarded so
# a missing dist/ (API-only local dev, e.g. `npm run dev` + uvicorn) doesn't crash.
#
# Routing order matters: the /api routers and /api/health above are registered
# first, so they always win; everything else falls through to the SPA below.
SPA_DIST_DIR = Path(os.getenv("SPA_DIST_DIR") or Path(__file__).resolve().parent.parent / "dist")

if (SPA_DIST_DIR / "index.html").is_file():
    logger.info("Serving built SPA from %s", SPA_DIST_DIR)

    if (SPA_DIST_DIR / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(SPA_DIST_DIR / "assets")),
            name="spa-assets",
        )

    _spa_index = SPA_DIST_DIR / "index.html"

    @app.get("/", include_in_schema=False)
    async def spa_root() -> FileResponse:
        return FileResponse(_spa_index)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # Unknown /api/* paths should 404 as API calls, not silently return HTML.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Serve real build files (favicon.svg, icons.svg, landing-tracker.js, ...).
        candidate = (SPA_DIST_DIR / full_path).resolve()
        if candidate.is_file() and SPA_DIST_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        # Otherwise this is a client-side route — hand back the SPA shell.
        return FileResponse(_spa_index)
else:
    logger.info("SPA build not found at %s — running API-only.", SPA_DIST_DIR)

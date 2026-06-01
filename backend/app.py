"""Meta Ad Agent API entrypoint.

This module is the composition root: it builds the FastAPI app, configures CORS,
and mounts the domain routers from backend/routers/. Endpoint logic lives in the
routers and the service modules they depend on.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import agents as agents_router
from .routers import approvals as approvals_router
from .routers import crm as crm_router
from .routers import dashboard as dashboard_router
from .routers import funnel as funnel_router
from .routers import meta as meta_router
from .routers import monitoring as monitoring_router
from .routers import planning as planning_router
from .routers import tasks as tasks_router
from .routers import telegram as telegram_router

app = FastAPI(title="Meta Ad Agent API")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FUNNEL_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    agents_router,
):
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

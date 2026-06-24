"""Dashboard payload routes (JSON + optional JSONP bootstrap)."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from .. import dashboard_service

router = APIRouter()


@router.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return dashboard_service.build_dashboard()


@router.get("/api/dashboard.js")
def dashboard_script(callback: str = "__META_AD_AGENT_DASHBOARD__") -> Response:
    # JSONP bypasses CORS (any site can read this via <script src>), so it would leak
    # campaign spend/audience data cross-origin. Disabled by default; the SPA uses the
    # CORS-protected /api/dashboard fetch (same-origin via the dev proxy). Enable only
    # for a trusted same-origin bootstrap.
    if os.getenv("DASHBOARD_JSONP_ENABLED", "").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="JSONP dashboard endpoint is disabled.")
    safe_callback = "".join(character for character in callback if character.isalnum() or character in "._$")
    if not safe_callback:
        safe_callback = "__META_AD_AGENT_DASHBOARD__"
    return Response(
        content=f"{safe_callback}({json.dumps(dashboard_service.build_dashboard(), ensure_ascii=False)});",
        media_type="application/javascript",
    )

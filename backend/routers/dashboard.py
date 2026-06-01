"""Dashboard payload routes (JSON + JSONP bootstrap)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Response

from .. import dashboard_service

router = APIRouter()


@router.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return dashboard_service.build_dashboard()


@router.get("/api/dashboard.js")
def dashboard_script(callback: str = "__META_AD_AGENT_DASHBOARD__") -> Response:
    safe_callback = "".join(character for character in callback if character.isalnum() or character in "._$")
    if not safe_callback:
        safe_callback = "__META_AD_AGENT_DASHBOARD__"
    return Response(
        content=f"{safe_callback}({json.dumps(dashboard_service.build_dashboard(), ensure_ascii=False)});",
        media_type="application/javascript",
    )

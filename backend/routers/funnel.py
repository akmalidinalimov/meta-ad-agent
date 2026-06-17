"""Landing-page / ChatPlace funnel event ingestion routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..api_models import FunnelEventRequest
from ..chatplace_events import normalize_chatplace_event
from ..funnel_events import build_funnel_summary, save_funnel_event

router = APIRouter()


@router.post("/api/funnel/events")
def ingest_funnel_event(request: FunnelEventRequest) -> dict[str, Any]:
    event = save_funnel_event(request.event)
    return {"ok": True, "event": event, "summary": build_funnel_summary()}


@router.post("/api/chatplace/events")
async def ingest_chatplace_event(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    expected_secret = os.getenv("CHATPLACE_WEBHOOK_SECRET", "").strip()
    provided_secret = str(payload.get("secret") or request.headers.get("x-chatplace-secret") or "").strip()
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid ChatPlace webhook secret.")

    event_payload = normalize_chatplace_event(payload)
    event = save_funnel_event(event_payload)
    return {
        "ok": True,
        "tracking_status": "saved",
        "visitor_id": event.get("visitorId"),
        "event_name": event.get("eventName"),
        "telegram_user_id": event.get("telegramUserId"),
        "summary": build_funnel_summary(),
    }


@router.get("/api/funnel/summary")
def funnel_event_summary() -> dict[str, Any]:
    return build_funnel_summary()

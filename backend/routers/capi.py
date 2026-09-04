"""Conversions API relay — the bot reports a captured phone, Meta gets a matchable event.

Called by the ChatPlace `http_request` action that sits next to `request_phone`, so it must
authenticate the same way /api/chatplace/events does (CHATPLACE_WEBHOOK_SECRET), not with a
dashboard session.

Status codes are deliberate, because ChatPlace's `httpRequestTags` marks the subscriber on any
non-2xx and that tag is the only visibility into a silently failing webhook:

  200  event sent, or recorded-but-unmatched (no token — a real gap, but retrying won't fix it)
  401  bad/missing secret
  502  Meta rejected the event — worth surfacing as a failed webhook so it gets noticed
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..capi_bridge import (
    build_capi_event,
    extract_token,
    is_matchable,
    lookup_identity,
    match_keys,
    send_capi_events,
)
from ..funnel_events import save_funnel_event
from ..meta_client import MetaApiError, get_meta_config

router = APIRouter()

DEFAULT_EVENT_NAME = "CRMLead"


def _authorize(payload: dict[str, Any], request: Request) -> None:
    expected = os.getenv("CHATPLACE_WEBHOOK_SECRET", "").strip()
    provided = str(payload.get("secret") or request.headers.get("x-chatplace-secret") or "").strip()
    if expected and provided != expected:
        raise HTTPException(status_code=401, detail="Invalid ChatPlace webhook secret.")


@router.post("/api/capi/lead")
async def capi_lead(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    _authorize(payload, request)

    token = extract_token(
        payload.get("start_payload")
        or payload.get("startPayload")
        or payload.get("token")
        or payload.get("visitor_id")
    )
    identity = lookup_identity(token)
    event_name = str(payload.get("event_name") or os.getenv("META_CAPI_EVENT_NAME", DEFAULT_EVENT_NAME)).strip()

    event = build_capi_event(
        event_name=event_name,
        token=token,
        phone=payload.get("phone"),
        first_name=payload.get("name") or payload.get("first_name"),
        identity=identity,
        aud=payload.get("aud"),
    )
    matchable = is_matchable(event)

    # Record it on the funnel either way, so the dashboard shows in-bot captures even when
    # the token bridge is not yet working end to end.
    save_funnel_event(
        {
            "event_name": "crm_form_submit",
            "visitor_id": token,
            "telegram_username": payload.get("telegram"),
            "source": "chatplace_capi",
            "matched": matchable,
        }
    )

    if payload.get("dry_run"):
        return {
            "ok": True,
            "sent": False,
            "dryRun": True,
            "matched": matchable,
            "token": token,
            "matchKeys": match_keys(event),
            "event": event,
        }

    config = get_meta_config()
    try:
        result = await send_capi_events(
            config,
            [event],
            test_event_code=payload.get("test_event_code"),
        )
    except MetaApiError as error:
        # 502 so ChatPlace tags the subscriber and the failure is visible rather than silent.
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "ok": True,
        "sent": True,
        "matched": matchable,
        "token": token,
        "matchKeys": match_keys(event),
        "eventsReceived": result.get("events_received"),
        "fbtraceId": result.get("fbtrace_id"),
    }

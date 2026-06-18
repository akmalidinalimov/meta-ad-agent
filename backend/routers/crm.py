"""Bitrix24 CRM status, import, and stage-discovery routes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..bitrix_client import (
    HttpBitrixTransport,
    fetch_bitrix_leads,
    fetch_bitrix_statuses,
    get_bitrix_config,
)
from ..crm_funnel import build_crm_stage_breakdown
from ..crm_store import STORAGE_DIR as CRM_STORAGE_DIR
from ..crm_store import list_crm_leads, save_crm_leads

router = APIRouter()

_STAGES_CACHE: dict[str, Any] = {}
_STAGES_TTL_SECONDS = 90


def build_bitrix_transport(config: Any) -> Any:
    return HttpBitrixTransport(config)


@router.get("/api/crm/bitrix/status")
def bitrix_status() -> dict[str, Any]:
    config = get_bitrix_config()
    return {
        "configured": config.is_configured,
        "message": "Bitrix24 webhook URL configured." if config.is_configured else "Add BITRIX24_WEBHOOK_URL or BITRIX24_PORTAL_URL, BITRIX24_USER_ID, and BITRIX24_WEBHOOK_KEY.",
    }


@router.post("/api/crm/bitrix/import")
async def bitrix_import() -> dict[str, Any]:
    config = get_bitrix_config()
    if not config.is_configured:
        raise HTTPException(status_code=400, detail="Bitrix24 webhook URL is not configured.")
    try:
        leads = await fetch_bitrix_leads(transport=build_bitrix_transport(config))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Bitrix24 import failed: {exc}") from exc
    saved = save_crm_leads(leads, storage_dir=CRM_STORAGE_DIR)
    return {
        "ok": True,
        "imported": len(saved),
        "leads": saved,
    }


@router.get("/api/crm/bitrix/stages")
async def bitrix_stages(entity_id: str = "STATUS") -> dict[str, Any]:
    config = get_bitrix_config()
    if not config.is_configured:
        raise HTTPException(status_code=400, detail="Bitrix24 webhook URL is not configured.")
    try:
        stages = await fetch_bitrix_statuses(transport=build_bitrix_transport(config), entity_id=entity_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Bitrix24 stage discovery failed: {exc}") from exc
    return {
        "ok": True,
        "entityId": entity_id,
        "stages": stages,
    }


@router.get("/api/crm/leads")
def crm_leads() -> dict[str, Any]:
    return {"leads": list_crm_leads(storage_dir=CRM_STORAGE_DIR)}


@router.get("/api/crm/stages")
async def crm_stages(days: int = 30) -> dict[str, Any]:
    """Bitrix lead stage distribution for the configured order/source (default: leads
    titled 'AI Creators 5.0 buyurtmasi'). Read-only, additive, TTL-cached."""
    config = get_bitrix_config()
    if not config.is_configured:
        return {
            "ok": False,
            "error": "Bitrix24 webhook URL is not configured.",
            "stages": [],
            "total": 0,
            "paid": 0,
            "paidStageIds": [],
            "source": "",
        }

    title = os.getenv("BITRIX_LEAD_SOURCE_TITLE", "AI Creators 5.0 buyurtmasi").strip()
    cache_key = f"{title}:{days}"
    now = datetime.now(timezone.utc)
    cached = _STAGES_CACHE.get(cache_key)
    if cached and (now - cached["at"]).total_seconds() < _STAGES_TTL_SECONDS:
        return cached["payload"]

    transport = build_bitrix_transport(config)
    try:
        leads = await fetch_bitrix_leads(transport=transport, days=days, limit=None, title_contains=title or None)
        stages_raw = await fetch_bitrix_statuses(transport=transport, entity_id="STATUS")
    except Exception as exc:  # noqa: BLE001 - surface a sanitized 502
        raise HTTPException(status_code=502, detail=f"Bitrix24 stages read failed: {exc}") from exc

    stages = [{"id": row["statusId"], "name": row["name"]} for row in stages_raw]
    paid_ids = [item.strip() for item in os.getenv("BITRIX_PAID_STATUS_IDS", "").split(",") if item.strip()]
    payload = build_crm_stage_breakdown(leads, stages=stages, paid_status_ids=paid_ids or None)
    payload["ok"] = True
    payload["source"] = title
    payload["days"] = days
    payload["refreshedAt"] = now.isoformat()
    _STAGES_CACHE[cache_key] = {"at": now, "payload": payload}
    return payload

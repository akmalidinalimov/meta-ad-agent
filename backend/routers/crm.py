"""Bitrix24 CRM status, import, and stage-discovery routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..bitrix_client import (
    HttpBitrixTransport,
    fetch_bitrix_leads,
    fetch_bitrix_statuses,
    get_bitrix_config,
)
from ..crm_store import STORAGE_DIR as CRM_STORAGE_DIR
from ..crm_store import list_crm_leads, save_crm_leads

router = APIRouter()


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

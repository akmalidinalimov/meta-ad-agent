"""Bitrix24 CRM status, import, and stage-discovery routes."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..bitrix_client import (
    HttpBitrixTransport,
    fetch_bitrix_leads,
    fetch_bitrix_statuses,
    get_bitrix_config,
    get_bot_cell_tags,
    tashkent_day,
)
from ..crm_funnel import build_crm_stage_breakdown, split_by_cell
from ..crm_store import STORAGE_DIR as CRM_STORAGE_DIR
from ..crm_store import list_crm_leads, save_crm_leads

router = APIRouter()

_STAGES_CACHE: dict[str, Any] = {}
_STAGES_TTL_SECONDS = 90


def build_bitrix_transport(config: Any) -> Any:
    return HttpBitrixTransport(config)


# Bucket Bitrix leads on Asia/Tashkent days (their DATE_CREATE carries a +03:00 offset).
# Shared with funnel_history + daily_analyst so every lead-day count uses the same boundary.
_lead_day = tashkent_day


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


def _parse_day(value: str | None) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def _account_spend(since_iso: str, until_iso: str) -> float:
    """Account-wide Meta spend for [since, until]. Best-effort -> 0.0 on any failure, so a
    Meta hiccup never blocks the CRM stages read."""
    try:
        from ..meta_client import get_insights, get_meta_config
        config = get_meta_config()
        if not config.is_configured:
            return 0.0
        rows = await get_insights(config, level="account", since=since_iso, until=until_iso, time_increment=None)
        return round(sum(_safe_float(row.get("spend")) for row in rows), 2)
    except Exception:  # noqa: BLE001 - spend is additive; CRM stages still return without it
        return 0.0


@router.get("/api/crm/stages")
async def crm_stages(
    days: int = 30,
    since: str | None = None,
    until: str | None = None,
    cell: str = "all",
    force: bool = False,
) -> dict[str, Any]:
    """Bitrix lead stage distribution for the configured order/source (default: leads
    titled 'AI Creators 5.0 buyurtmasi'). Read-only, additive, TTL-cached.

    ``cell`` selects which origin to count: 'B' = Telegram-bot VSL form only (the bot
    leads), 'A' = the same form used elsewhere, 'all' = both. The window is the last
    ``days`` days, or an explicit ``since``..``until`` (YYYY-MM-DD) range. ``cellCounts``
    always reports the A/B/all split for the window so the UI can show it."""
    config = get_bitrix_config()
    cell = (cell or "all").strip().upper()
    if cell not in ("A", "B", "ALL"):
        cell = "ALL"
    if not config.is_configured:
        return {
            "ok": False,
            "error": "Bitrix24 webhook URL is not configured.",
            "stages": [],
            "total": 0,
            "paid": 0,
            "paidStageIds": [],
            "source": "",
            "cell": cell,
            "cellCounts": {"A": 0, "B": 0, "all": 0},
        }

    title = os.getenv("BITRIX_LEAD_SOURCE_TITLE", "AI Creators 5.0 buyurtmasi").strip()
    # Resolve the window: an explicit since..until wins; else the last N days.
    end_day = _parse_day(until) or date.today()
    start_day = _parse_day(since)
    if start_day and start_day <= end_day:
        fetch_days = (date.today() - start_day).days + 1
    else:
        fetch_days = days
        start_day = end_day - timedelta(days=days - 1)

    cache_key = f"{title}:{start_day}:{end_day}:{cell}"
    now = datetime.now(timezone.utc)
    cached = _STAGES_CACHE.get(cache_key)
    if not force and cached and (now - cached["at"]).total_seconds() < _STAGES_TTL_SECONDS:
        return cached["payload"]

    transport = build_bitrix_transport(config)
    try:
        leads = await fetch_bitrix_leads(transport=transport, days=fetch_days, limit=None, title_contains=title or None)
        stages_raw = await fetch_bitrix_statuses(transport=transport, entity_id="STATUS")
    except Exception as exc:  # noqa: BLE001 - surface a sanitized 502
        raise HTTPException(status_code=502, detail=f"Bitrix24 stages read failed: {exc}") from exc

    # Clamp to the requested window, bucketing each lead on its Asia/Tashkent calendar day
    # (Bitrix timestamps carry a +03:00 offset) so the lead-day aligns with the Tashkent
    # spend-day — otherwise late-night Tashkent leads leak to the previous day.
    lo, hi = start_day.isoformat(), end_day.isoformat()
    window = [lead for lead in leads if lo <= _lead_day(lead.get("createdAt")) <= hi]

    descs, utms = get_bot_cell_tags()
    split = split_by_cell(window, bot_source_descriptions=descs, bot_utm_contents=utms)
    cell_counts = {"A": len(split["A"]), "B": len(split["B"]), "all": len(window)}
    selected = split["B"] if cell == "B" else split["A"] if cell == "A" else window

    stages = [{"id": row["statusId"], "name": row["name"]} for row in stages_raw]
    paid_ids = [item.strip() for item in os.getenv("BITRIX_PAID_STATUS_IDS", "").split(",") if item.strip()]
    payload = build_crm_stage_breakdown(selected, stages=stages, paid_status_ids=paid_ids or None)
    payload["ok"] = True
    payload["source"] = title
    payload["days"] = fetch_days
    payload["since"] = lo
    payload["until"] = hi
    payload["cell"] = cell
    payload["cellCounts"] = cell_counts
    payload["botTags"] = {"sourceDescriptions": descs, "utmContents": utms}

    # Cost per REAL CRM lead = account Meta spend (same window) ÷ ALL CRM leads that landed.
    # Account-level by design: Bitrix leads carry no campaign key, so this can't be split per
    # campaign (the date filter still applies fully). costPerSale uses paid leads — the truest
    # cost metric per the funnel playbook. Both use the ALL-leads window, independent of `cell`.
    all_total = cell_counts["all"]
    all_paid = payload["paid"] if cell == "ALL" else build_crm_stage_breakdown(
        window, stages=stages, paid_status_ids=paid_ids or None
    )["paid"]
    spend = await _account_spend(lo, hi)
    payload["spend"] = spend
    payload["leadsAll"] = all_total
    payload["paidAll"] = all_paid
    payload["costPerLead"] = round(spend / all_total, 2) if all_total else None
    payload["costPerSale"] = round(spend / all_paid, 2) if all_paid else None

    payload["refreshedAt"] = now.isoformat()
    _STAGES_CACHE[cache_key] = {"at": now, "payload": payload}
    return payload

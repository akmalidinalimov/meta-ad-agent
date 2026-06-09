"""Meta Ads MCP server (Streamable HTTP) for the Claude.ai Project connector.

Granular, always-live tools over the existing async meta_client. Reads are
instant/fresh; writes are gated — reversible edits apply directly, destructive
ones require confirm=True. Secured by an unguessable mount path + HTTPS; all
writes additionally gated by META_LIVE_WRITES_ENABLED.
"""
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .adset_creatives import fetch_adset_creatives, rank_creatives, serialize_creative
from .campaign_specific_analysis import find_campaign
from .config import live_writes_enabled
from .knowledge_base import load_knowledge_base
from .meta_client import (
    MetaApiError,
    get_ad_account_summary,
    get_ad_sets,
    get_insights,
    get_meta_config,
    update_ad_set,
    update_campaign,
)
from .meta_live import get_live_account

_DESTRUCTIVE_BUDGET_FRACTION = 0.25

# The connector is reached through Caddy (Host = the public sslip.io domain) and
# Claude.ai connects server-side, so MCP's default localhost-only DNS-rebinding
# guard would 421 every real request. Our security boundary is the unguessable
# secret mount path + HTTPS + the write gates, so disable the host/origin check.
mcp = FastMCP(
    "Meta Ads",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def requires_confirmation(action: str, change: dict[str, Any], current: dict[str, Any]) -> bool:
    if action == "update_status":
        status = str(change.get("status") or "").upper()
        if status == "ARCHIVED":
            return True
        if status == "PAUSED" and str(current.get("effective_status") or "").upper() == "ACTIVE":
            return True
        return False
    if action == "update_budget":
        try:
            new = float(change.get("new_usd"))
            cur = float(current.get("current_usd"))
        except (TypeError, ValueError):
            return True
        if cur <= 0:
            return True
        return abs(new - cur) / cur > _DESTRUCTIVE_BUDGET_FRACTION
    return False


# --- Read helpers -------------------------------------------------------------
#
# Helpers `await` meta_client directly (FastMCP runs them in the event loop — no
# asyncio.run). Kept separate from the @mcp.tool() wrappers so tests can call
# them directly and monkeypatch the module-level meta_client references.


async def _list_campaigns(status: str | None = None) -> dict[str, Any]:
    acct = await get_live_account(knowledge=load_knowledge_base() or {})
    camps = acct.campaigns
    if status:
        s = status.upper()
        camps = [c for c in camps if str(c.get("effective_status") or c.get("status") or "").upper() == s]
    return {"source": acct.source, "count": len(camps), "campaigns": camps}


async def _get_campaign(name_or_id: str) -> dict[str, Any]:
    acct = await get_live_account(knowledge=load_knowledge_base() or {})
    match = find_campaign(name_or_id, {}, campaigns=acct.campaigns)
    if not match:
        return {"found": False, "message": f"No campaign matching '{name_or_id}'.",
                "candidates": [c.get("name") for c in acct.campaigns[:15]]}
    cid = match["id"]
    full = next((c for c in acct.campaigns if str(c.get("id")) == cid), match)
    adsets = [a for a in acct.adsets if str(a.get("campaign_id")) == cid]
    studies = [s for s in acct.adstudies if _study_touches_campaign(s, cid, adsets)]
    names = {str(a.get("id")): a.get("name") for a in acct.saved_audiences if a.get("id")}
    return {"source": acct.source, "campaign": full,
            "adsets": [_render_adset(a, names) for a in adsets],
            "abTest": ({"name": studies[0].get("name")} if studies else None)}


async def _get_adset_creatives(adset_id: str) -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"configured": False, "creatives": []}
    try:
        ranked = await fetch_adset_creatives(config, adset_id)
        source = "live"
    except MetaApiError as error:
        knowledge = load_knowledge_base() or {}
        ads = [a for a in (knowledge.get("raw", {}).get("ads", []) or []) if str(a.get("adset_id")) == str(adset_id)]
        ranked = rank_creatives(ads, [])
        source = "snapshot"
        return {"configured": True, "source": source, "error": str(error),
                "creatives": [serialize_creative(a) for a in ranked]}
    return {"configured": True, "source": source, "creatives": [serialize_creative(a) for a in ranked]}


# Compact per-row projection so deep breakdown queries don't blow the context.
# (The raw insights row carries large video_* arrays + action_values we drop here.)
_INSIGHT_KEEP = (
    "campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name",
    "age", "gender", "country", "region", "publisher_platform", "platform_position",
    "impressions", "reach", "spend", "clicks", "ctr", "cpc", "cpm", "actions",
)
_INSIGHT_ROW_CAP = 300


async def _get_insights(level: str, object_id: str | None = None,
                        breakdowns: list[str] | None = None, date_preset: str = "maximum") -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"rows": [], "configured": False}
    # Aggregate over the whole window (time_increment=None) instead of per-day rows —
    # keeps breakdown queries small enough for the Project's context.
    rows = await get_insights(config, level=level, breakdowns=breakdowns,
                              date_preset=date_preset, time_increment=None)
    if object_id:
        key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}.get(level)
        if key:
            rows = [r for r in rows if r.get(key) is None or str(r.get(key)) == str(object_id)]
    trimmed = [{k: r[k] for k in _INSIGHT_KEEP if k in r} for r in rows]
    truncated = len(trimmed) > _INSIGHT_ROW_CAP
    return {
        "level": level, "object_id": object_id, "breakdowns": breakdowns or [],
        "date_preset": date_preset, "row_count": len(trimmed), "truncated": truncated,
        "rows": trimmed[:_INSIGHT_ROW_CAP],
        **({"note": f"Showing first {_INSIGHT_ROW_CAP} of {len(trimmed)} rows — narrow with object_id or a breakdown."} if truncated else {}),
    }


async def _search(query: str) -> dict[str, Any]:
    acct = await get_live_account(knowledge=load_knowledge_base() or {})
    q = query.lower()
    camps = [c for c in acct.campaigns if q in str(c.get("name") or "").lower()]
    adsets = [a for a in acct.adsets if q in str(a.get("name") or "").lower()]
    return {"campaigns": camps[:25], "adsets": adsets[:25]}


async def _account_summary() -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"configured": False}
    try:
        return {"configured": True, "account": await get_ad_account_summary(config)}
    except MetaApiError as error:
        return {"configured": True, "error": str(error)}


def _render_adset(adset: dict[str, Any], audience_names: dict[str, str]) -> dict[str, Any]:
    targeting = adset.get("targeting") or {}
    flex = targeting.get("flexible_spec") or []
    interests = [i.get("name") for spec in flex for i in (spec.get("interests") or []) if i.get("name")]
    customs = [audience_names.get(str(c.get("id")), str(c.get("id"))) for c in (targeting.get("custom_audiences") or [])]
    geo = targeting.get("geo_locations") or {}
    return {
        "id": adset.get("id"), "name": adset.get("name"),
        "status": adset.get("effective_status") or adset.get("status"),
        "optimization_goal": adset.get("optimization_goal"),
        "billing_event": adset.get("billing_event"), "bid_strategy": adset.get("bid_strategy"),
        "daily_budget_usd": _cents_to_usd(adset.get("daily_budget")),
        "is_dynamic_creative": adset.get("is_dynamic_creative"),
        "age": {"min": targeting.get("age_min"), "max": targeting.get("age_max")},
        "geo": {"countries": geo.get("countries"), "regions": [r.get("name") for r in (geo.get("regions") or [])],
                "cities": [c.get("name") for c in (geo.get("cities") or [])]},
        "placements": {"platforms": targeting.get("publisher_platforms"),
                       "instagram_positions": targeting.get("instagram_positions"),
                       "facebook_positions": targeting.get("facebook_positions")},
        "interests": interests, "custom_audiences": customs,
    }


def _study_touches_campaign(study: dict[str, Any], campaign_id: str, adsets: list[dict[str, Any]]) -> bool:
    adset_ids = {str(a.get("id")) for a in adsets}
    cells = study.get("cells")
    cells = cells.get("data", []) if isinstance(cells, dict) else (cells or [])
    for cell in cells:
        cell_adsets = cell.get("adsets")
        cell_adsets = cell_adsets.get("data", []) if isinstance(cell_adsets, dict) else (cell_adsets or [])
        for a in cell_adsets:
            if str(a.get("campaign_id")) == str(campaign_id) or str(a.get("id")) in adset_ids:
                return True
    return False


def _cents_to_usd(value: Any) -> float | None:
    try:
        return round(float(value) / 100, 2)
    except (TypeError, ValueError):
        return None


# --- Write helpers ------------------------------------------------------------


async def _find_entity(level: str, entity_id: str) -> dict[str, Any] | None:
    acct = await get_live_account(knowledge=load_knowledge_base() or {})
    pool = acct.campaigns if level == "campaign" else acct.adsets
    return next((e for e in pool if str(e.get("id")) == str(entity_id)), None)


async def _update_status(level: str, entity_id: str, status: str, confirm: bool = False) -> dict[str, Any]:
    if not live_writes_enabled():
        return {"ok": False, "error": "Live writes are disabled by config (META_LIVE_WRITES_ENABLED)."}
    status = status.upper()
    if status not in {"ACTIVE", "PAUSED", "ARCHIVED"}:
        return {"ok": False, "error": "status must be ACTIVE, PAUSED, or ARCHIVED."}
    current = await _find_entity(level, entity_id) or {}
    if requires_confirmation("update_status", {"status": status}, current) and not confirm:
        return {"needsConfirmation": True,
                "preview": {"level": level, "id": entity_id, "name": current.get("name"),
                            "from": current.get("effective_status"), "to": status},
                "message": f"This will set {current.get('name') or entity_id} to {status}. Re-call with confirm=true to apply."}
    config = get_meta_config()
    writer = update_campaign if level == "campaign" else update_ad_set
    try:
        await writer(config, str(entity_id), {"status": status})
    except MetaApiError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "level": level, "id": entity_id, "status": status}


async def _update_budget(adset_id: str, daily_budget_usd: float, confirm: bool = False) -> dict[str, Any]:
    if not live_writes_enabled():
        return {"ok": False, "error": "Live writes are disabled by config (META_LIVE_WRITES_ENABLED)."}
    current = await _find_entity("adset", adset_id) or {}
    current_usd = _cents_to_usd(current.get("daily_budget")) or 0.0
    if requires_confirmation("update_budget", {"new_usd": daily_budget_usd}, {"current_usd": current_usd}) and not confirm:
        return {"needsConfirmation": True,
                "preview": {"id": adset_id, "name": current.get("name"), "from_usd": current_usd, "to_usd": daily_budget_usd},
                "message": f"This will change {current.get('name') or adset_id} budget from ${current_usd:.2f} to ${daily_budget_usd:.2f}. Re-call with confirm=true to apply."}
    config = get_meta_config()
    try:
        await update_ad_set(config, str(adset_id), {"daily_budget": int(round(float(daily_budget_usd) * 100))})
    except (MetaApiError, ValueError) as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "id": adset_id, "daily_budget_usd": daily_budget_usd}


# --- Tool registrations -------------------------------------------------------
#
# The @mcp.tool() functions are thin wrappers over the helpers above. The insights
# tool is deliberately named `insights` (not `get_insights`) so the module attribute
# `get_insights` stays bound to meta_client's imported function — both `_get_insights`
# and the tests rely on that binding.


@mcp.tool()
async def list_campaigns(status: str | None = None) -> dict[str, Any]:
    """List campaigns (live). Optional status filter: ACTIVE | PAUSED | ARCHIVED."""
    return await _list_campaigns(status)


@mcp.tool()
async def get_campaign(name_or_id: str) -> dict[str, Any]:
    """Full live config of one campaign: ad sets, targeting (age/geo/interests/custom-audience names/placements), optimization/billing/bid, A/B-test status."""
    return await _get_campaign(name_or_id)


@mcp.tool()
async def get_adset_creatives(adset_id: str) -> dict[str, Any]:
    """Creatives for an ad set, ranked by lifetime performance, with stats + thumbnails + video links."""
    return await _get_adset_creatives(adset_id)


@mcp.tool()
async def insights(level: str, object_id: str | None = None,
                   breakdowns: list[str] | None = None, date_preset: str = "maximum") -> dict[str, Any]:
    """Live performance, AGGREGATED over the date window (not per-day). level: campaign|adset|ad. Pass object_id to scope to one entity. breakdowns: any of age, gender, country, region, publisher_platform, platform_position. date_preset e.g. last_7d, last_30d, maximum. Returns {rows, row_count, truncated}; narrow with object_id/breakdown if truncated."""
    return await _get_insights(level, object_id, breakdowns, date_preset)


@mcp.tool()
async def search(query: str) -> dict[str, Any]:
    """Find campaigns and ad sets by name fragment."""
    return await _search(query)


@mcp.tool()
async def account_summary() -> dict[str, Any]:
    """Ad account name, currency, and status."""
    return await _account_summary()


@mcp.tool()
async def update_status(level: str, id: str, status: str, confirm: bool = False) -> dict[str, Any]:
    """Set a campaign or ad set status. level: campaign|adset. status: ACTIVE|PAUSED|ARCHIVED. Destructive changes (ARCHIVED, or pausing a delivering entity) return needsConfirmation unless confirm=true."""
    return await _update_status(level, id, status, confirm)


@mcp.tool()
async def update_budget(adset_id: str, daily_budget_usd: float, confirm: bool = False) -> dict[str, Any]:
    """Set an ad set's daily budget (USD). Changes beyond ±25% return needsConfirmation unless confirm=true."""
    return await _update_budget(adset_id, daily_budget_usd, confirm)


# --- ASGI mount + secret path -------------------------------------------------


def mount_path() -> str:
    """Secret URL path the connector is mounted at. Unguessable token = the auth boundary."""
    secret = os.getenv("MCP_PATH_SECRET", "").strip()
    return f"/mcp/{secret}" if secret else ""


def streamable_app():
    """The ASGI (Starlette) app implementing Streamable HTTP for this MCP server."""
    return mcp.streamable_http_app()

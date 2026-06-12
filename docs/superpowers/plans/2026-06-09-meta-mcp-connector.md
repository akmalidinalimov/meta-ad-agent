# Meta Ads MCP Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the live Meta ad account as a Streamable-HTTP MCP server mounted in the existing FastAPI app, so a Claude.ai Project (custom connector) can answer deep ad-hoc questions from fresh data and make gated edits.

**Architecture:** A FastMCP server defines granular tools that `await` the existing async `meta_client` functions (always live). It is mounted in `backend/app.py` at a secret path `/mcp/<MCP_PATH_SECRET>` (unguessable URL = the auth boundary — no OAuth, per Claude.ai's "OAuth optional" rule). Caddy already proxies the app over HTTPS. Writes are server-gated: reversible edits apply directly; destructive ones (archive, pausing an active entity, budget Δ>25%) return a preview unless `confirm=true`. `META_LIVE_WRITES_ENABLED` still gates all writes.

**Tech Stack:** Python `mcp` SDK (FastMCP, Streamable HTTP), FastAPI/Starlette mount + lifespan, existing `backend/meta_client.py` / `meta_live.py` / `adset_creatives.py`.

**Security note:** the secret path is a bearer-secret-in-URL. Use a 32-byte URL-safe token in `MCP_PATH_SECRET`, HTTPS only, rotate if leaked. This is acceptable for a single-operator personal tool; full OAuth 2.1+PKCE can be added later as hardening (out of scope for v1).

---

## File Structure

- Create `backend/mcp_server.py` — FastMCP instance, all tool definitions, write-safety helper. One responsibility: expose Meta tools over MCP.
- Modify `backend/app.py` — mount the MCP ASGI app at `/mcp/<secret>`; wire its session-manager lifespan into the app lifespan. Confirm the session-guard middleware does not gate `/mcp...`.
- Modify `backend/requirements.txt` (or `pyproject`) — add `mcp`.
- Create `backend/test_mcp_server.py` — unit tests for tool wrappers + write-safety (monkeypatch meta_client).
- Modify `docs/meta-project/setup.md` — real connector URL form + "no OAuth, paste the secret URL" steps.
- VM: `pip install mcp`, set `MCP_PATH_SECRET` in `.env`, restart, verify, hand operator the URL.

---

## Task 1: Add the `mcp` dependency

**Files:** Modify `backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:

```
mcp>=1.2.0
```

- [ ] **Step 2: Install locally and confirm import**

Run: `python -c "from mcp.server.fastmcp import FastMCP; print('ok')"`
Expected: `ok` (install with `pip install "mcp>=1.2.0"` first if missing)

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "build: add mcp SDK dependency for the connector"
```

---

## Task 2: Write-safety helper (TDD)

**Files:** Create `backend/mcp_server.py`; Test `backend/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/test_mcp_server.py
import backend.mcp_server as mcp_server


def test_requires_confirmation_rules():
    # Archive is always destructive.
    assert mcp_server.requires_confirmation("update_status", {"status": "ARCHIVED"}, {"effective_status": "PAUSED"}) is True
    # Pausing an ACTIVE (delivering) entity is destructive.
    assert mcp_server.requires_confirmation("update_status", {"status": "PAUSED"}, {"effective_status": "ACTIVE"}) is True
    # Pausing an already-paused entity is reversible/no-op -> no confirm.
    assert mcp_server.requires_confirmation("update_status", {"status": "PAUSED"}, {"effective_status": "PAUSED"}) is False
    # Reactivating is reversible.
    assert mcp_server.requires_confirmation("update_status", {"status": "ACTIVE"}, {"effective_status": "PAUSED"}) is False
    # Budget change within 25% is fine; beyond 25% needs confirm.
    assert mcp_server.requires_confirmation("update_budget", {"new_usd": 11.0}, {"current_usd": 10.0}) is False
    assert mcp_server.requires_confirmation("update_budget", {"new_usd": 20.0}, {"current_usd": 10.0}) is True
    # No current budget known -> be safe, confirm.
    assert mcp_server.requires_confirmation("update_budget", {"new_usd": 20.0}, {"current_usd": 0.0}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_mcp_server.py::test_requires_confirmation_rules -v`
Expected: FAIL (module/function not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/mcp_server.py
"""Meta Ads MCP server (Streamable HTTP) for the Claude.ai Project connector.

Granular, always-live tools over the existing async meta_client. Reads are
instant/fresh; writes are gated — reversible edits apply directly, destructive
ones require confirm=True. Secured by an unguessable mount path + HTTPS; all
writes additionally gated by META_LIVE_WRITES_ENABLED.
"""
from __future__ import annotations

from typing import Any

_DESTRUCTIVE_BUDGET_FRACTION = 0.25


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_mcp_server.py::test_requires_confirmation_rules -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/mcp_server.py backend/test_mcp_server.py
git commit -m "feat(mcp): write-safety helper for destructive-edit gating"
```

---

## Task 3: Read tools (TDD per tool, grouped)

**Files:** Modify `backend/mcp_server.py`; Test `backend/test_mcp_server.py`

Read tools `await` meta_client directly (FastMCP runs them in the event loop — no `asyncio.run`). Each returns plain JSON-able dicts/lists. Reuse: `meta_live.get_live_account` for roster/config context, `adset_creatives.fetch_adset_creatives` + `serialize_creative` for ranked creatives, `meta_client.get_insights` for breakdowns, `campaign_specific_analysis.find_campaign` for name resolution.

- [ ] **Step 1: Write failing tests**

```python
import asyncio
from types import SimpleNamespace
import backend.mcp_server as mcp_server


def test_list_campaigns_returns_live(monkeypatch):
    async def fake_live(**kwargs):
        return SimpleNamespace(
            campaigns=[{"id": "1", "name": "Income", "status": "ACTIVE", "effective_status": "ACTIVE",
                        "objective": "OUTCOME_LEADS", "daily_budget": "10000"}],
            adsets=[], ads=[], adstudies=[], saved_audiences=[], source="live",
        )
    monkeypatch.setattr(mcp_server, "get_live_account", fake_live)
    out = asyncio.run(mcp_server._list_campaigns(status=None))
    assert out["source"] == "live"
    assert out["campaigns"][0]["name"] == "Income"


def test_get_insights_passes_breakdowns(monkeypatch):
    captured = {}
    async def fake_insights(config, *, breakdowns=None, level="ad", date_preset="last_90d", **kw):
        captured["breakdowns"] = breakdowns
        captured["level"] = level
        return [{"age": "25-34", "spend": "5", "clicks": "10", "ctr": "2.0", "actions": []}]
    monkeypatch.setattr(mcp_server, "get_insights", fake_insights)
    monkeypatch.setattr(mcp_server, "get_meta_config", lambda: SimpleNamespace(is_configured=True, ad_account_id="act_1"))
    rows = asyncio.run(mcp_server._get_insights(level="campaign", object_id="1", breakdowns=["age"], date_preset="last_30d"))
    assert captured["breakdowns"] == ["age"]
    assert rows[0]["age"] == "25-34"
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest backend/test_mcp_server.py -k "list_campaigns or insights" -v`
Expected: FAIL (helpers not defined)

- [ ] **Step 3: Implement the read helpers + register as MCP tools**

Add to `backend/mcp_server.py`:

```python
from mcp.server.fastmcp import FastMCP

from .adset_creatives import fetch_adset_creatives, rank_creatives, serialize_creative
from .campaign_specific_analysis import find_campaign
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

mcp = FastMCP("Meta Ads")


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


async def _get_insights(level: str, object_id: str | None = None,
                        breakdowns: list[str] | None = None, date_preset: str = "maximum") -> list[dict[str, Any]]:
    config = get_meta_config()
    if not config.is_configured:
        return []
    rows = await get_insights(config, level=level, breakdowns=breakdowns, date_preset=date_preset)
    if object_id:
        key = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}.get(level)
        if key:
            rows = [r for r in rows if str(r.get(key)) == str(object_id)]
    return rows


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
```

Then register each as a tool (FastMCP wraps the helper; keep helpers separate so tests call them directly):

```python
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
                   breakdowns: list[str] | None = None, date_preset: str = "maximum") -> list[dict[str, Any]]:
    """Live performance rows. level: campaign|adset|ad. breakdowns: any of age, gender, country, region, publisher_platform, platform_position. date_preset e.g. last_7d, last_30d, maximum. (Tool is named `insights` so the module keeps `get_insights` bound to meta_client's function.)"""
    return await _get_insights(level, object_id, breakdowns, date_preset)


@mcp.tool()
async def search(query: str) -> dict[str, Any]:
    """Find campaigns and ad sets by name fragment."""
    return await _search(query)


@mcp.tool()
async def account_summary() -> dict[str, Any]:
    """Ad account name, currency, and status."""
    return await _account_summary()
```

> Note: the public tool `get_insights` shadows the imported `get_insights` from meta_client within the module namespace only after definition; the helper `_get_insights` captures the meta_client reference at call time via the module global. To avoid the shadow, import meta_client's function under an alias: `from .meta_client import get_insights as _mc_get_insights` and call `_mc_get_insights` inside `_get_insights`. Apply the same alias pattern the tests expect (tests monkeypatch `mcp_server.get_insights`) — so keep the module attribute `get_insights` bound to the meta_client function and name the TOOL differently, e.g. tool function `insights(...)`. Final decision: name the tool `insights` (not `get_insights`) to keep `mcp_server.get_insights` pointing at meta_client's function for both the helper and the tests.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest backend/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/mcp_server.py backend/test_mcp_server.py
git commit -m "feat(mcp): live read tools (campaigns, config, creatives, insights, search)"
```

---

## Task 4: Write tools with destructive-confirm (TDD)

**Files:** Modify `backend/mcp_server.py`; Test `backend/test_mcp_server.py`

- [ ] **Step 1: Write failing tests**

```python
def test_update_status_blocks_destructive_without_confirm(monkeypatch):
    async def fake_live(**kw):
        return SimpleNamespace(campaigns=[{"id": "1", "name": "Income", "effective_status": "ACTIVE"}],
                               adsets=[], ads=[], adstudies=[], saved_audiences=[], source="live")
    monkeypatch.setattr(mcp_server, "get_live_account", fake_live)
    monkeypatch.setattr(mcp_server, "live_writes_enabled", lambda: True)
    called = {"n": 0}
    async def fake_update(*a, **k):
        called["n"] += 1
        return {"id": "1"}
    monkeypatch.setattr(mcp_server, "update_campaign", fake_update)
    monkeypatch.setattr(mcp_server, "get_meta_config", lambda: SimpleNamespace(is_configured=True))
    out = asyncio.run(mcp_server._update_status("campaign", "1", "PAUSED", confirm=False))
    assert out["needsConfirmation"] is True
    assert called["n"] == 0  # nothing written


def test_update_status_applies_with_confirm(monkeypatch):
    async def fake_live(**kw):
        return SimpleNamespace(campaigns=[{"id": "1", "name": "Income", "effective_status": "ACTIVE"}],
                               adsets=[], ads=[], adstudies=[], saved_audiences=[], source="live")
    monkeypatch.setattr(mcp_server, "get_live_account", fake_live)
    monkeypatch.setattr(mcp_server, "live_writes_enabled", lambda: True)
    monkeypatch.setattr(mcp_server, "get_meta_config", lambda: SimpleNamespace(is_configured=True))
    async def fake_update(config, cid, payload):
        assert payload == {"status": "PAUSED"}
        return {"id": cid}
    monkeypatch.setattr(mcp_server, "update_campaign", fake_update)
    out = asyncio.run(mcp_server._update_status("campaign", "1", "PAUSED", confirm=True))
    assert out["ok"] is True


def test_writes_blocked_when_disabled(monkeypatch):
    monkeypatch.setattr(mcp_server, "live_writes_enabled", lambda: False)
    out = asyncio.run(mcp_server._update_status("campaign", "1", "PAUSED", confirm=True))
    assert out["ok"] is False
    assert "live writes" in out["error"].lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest backend/test_mcp_server.py -k update_status -v`
Expected: FAIL

- [ ] **Step 3: Implement write helpers + tools**

Add imports + helpers to `backend/mcp_server.py`:

```python
from .config import live_writes_enabled


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


@mcp.tool()
async def update_status(level: str, id: str, status: str, confirm: bool = False) -> dict[str, Any]:
    """Set a campaign or ad set status. level: campaign|adset. status: ACTIVE|PAUSED|ARCHIVED. Destructive changes (ARCHIVED, or pausing a delivering entity) return needsConfirmation unless confirm=true."""
    return await _update_status(level, id, status, confirm)


@mcp.tool()
async def update_budget(adset_id: str, daily_budget_usd: float, confirm: bool = False) -> dict[str, Any]:
    """Set an ad set's daily budget (USD). Changes beyond ±25% return needsConfirmation unless confirm=true."""
    return await _update_budget(adset_id, daily_budget_usd, confirm)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest backend/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/mcp_server.py backend/test_mcp_server.py
git commit -m "feat(mcp): gated write tools (update_status, update_budget)"
```

---

## Task 5: Mount the MCP app in FastAPI at a secret path

**Files:** Modify `backend/app.py` (and `backend/mcp_server.py` to expose the ASGI app + secret)

- [ ] **Step 1: Expose the streamable-HTTP app + secret in mcp_server.py**

Add at the end of `backend/mcp_server.py`:

```python
import os


def mount_path() -> str:
    """Secret URL path the connector is mounted at. Unguessable token = the auth boundary."""
    secret = os.getenv("MCP_PATH_SECRET", "").strip()
    return f"/mcp/{secret}" if secret else ""


def streamable_app():
    """The ASGI (Starlette) app implementing Streamable HTTP for this MCP server."""
    return mcp.streamable_http_app()
```

- [ ] **Step 2: Mount it + wire the session-manager lifespan in app.py**

In `backend/app.py`, after the FastAPI app is created and BEFORE `uvicorn` serves it, mount the MCP app when `MCP_PATH_SECRET` is set. FastMCP's streamable app has its own lifespan (the session manager) that MUST run, so combine it with the app's existing lifespan.

```python
# backend/app.py — near the top-level app wiring
from contextlib import asynccontextmanager
from . import mcp_server

_mcp_path = mcp_server.mount_path()
_mcp_app = mcp_server.streamable_app() if _mcp_path else None

# If the app already defines a lifespan, nest the MCP session manager inside it.
# If it does not, add this lifespan to FastAPI(lifespan=_lifespan).
@asynccontextmanager
async def _lifespan(app):
    if _mcp_app is not None:
        async with _mcp_app.router.lifespan_context(_mcp_app):
            yield
    else:
        yield

# app = FastAPI(lifespan=_lifespan)   # ensure the app is constructed with this lifespan
if _mcp_app is not None:
    app.mount(_mcp_path, _mcp_app)
```

If `app.py` already has startup logic (it registers the bot UI on startup and runs the monitoring scheduler), fold the MCP `lifespan_context` into that existing lifespan/startup so both run. Do NOT drop existing startup behavior.

- [ ] **Step 3: Confirm the session-guard middleware ignores `/mcp...`**

In `backend/app.py` the session guard gates `/api/*`. Verify `/mcp/...` is not matched (it isn't, since it's not under `/api`). Add an explicit early-return for paths starting with `/mcp/` in the guard middleware as a safety net:

```python
# inside the session-guard middleware, before the gate:
if request.url.path.startswith("/mcp/"):
    return await call_next(request)
```

- [ ] **Step 4: Test the app still imports and the MCP app builds**

Run: `MCP_PATH_SECRET=testsecret python -c "import backend.app as a; print('mounted', any(getattr(r,'path','').startswith('/mcp/testsecret') for r in a.app.routes))"`
Expected: prints `mounted True`

- [ ] **Step 5: Run the full backend suite**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: all pass (existing + new mcp tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app.py backend/mcp_server.py
git commit -m "feat(mcp): mount Streamable HTTP MCP at secret path with lifespan"
```

---

## Task 6: Update the operator setup doc

**Files:** Modify `docs/meta-project/setup.md`

- [ ] **Step 1: Replace the connector step with the real, no-OAuth flow**

Update the "Connect the Meta tool" section to:

```markdown
### 1. Connect the Meta tool
1. claude.ai → Settings → Connectors → Add custom connector.
2. Name: `Meta Ads`. URL: `https://82-70-42-188.sslip.io/mcp/<SECRET>` (Claude will give you the exact secret URL).
3. Leave Advanced settings / OAuth EMPTY — this connector uses a private secret URL, no OAuth.
4. Click Add. The Meta tools become available.

Security: the secret URL is your key — don't share it. If it leaks, rotate `MCP_PATH_SECRET` on the server and re-add the connector with the new URL.
```

- [ ] **Step 2: Commit**

```bash
git add docs/meta-project/setup.md
git commit -m "docs(meta-project): real no-OAuth secret-URL connector setup steps"
```

---

## Task 7: Deploy + configure + live-verify (infra; orchestrator-run)

These steps run against the VM and Claude.ai; they are not unit-testable.

- [ ] **Step 1:** On the VM, install the dep: `pip install "mcp>=1.2.0"` (or into the service's interpreter `/usr/bin/python3.11 -m pip install ...`).
- [ ] **Step 2:** Generate a secret and add to `~/meta-ad-agent/.env`: `MCP_PATH_SECRET=$(python3.11 -c "import secrets;print(secrets.token_urlsafe(32))")`. Record the value.
- [ ] **Step 3:** Deploy the changed `backend/` (build local → tar → scp → `tar xzf`), `sudo systemctl restart meta-ad-agent`, `curl http://127.0.0.1:8000/api/health` → ok.
- [ ] **Step 4:** Verify the MCP endpoint responds to an MCP `initialize` POST locally: `curl -s -X POST http://127.0.0.1:8000/mcp/<SECRET> -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'` → expect a JSON-RPC InitializeResult (and an `Mcp-Session-Id` header).
- [ ] **Step 5:** Verify Caddy proxies `/mcp/...` over HTTPS (it uses a catch-all reverse_proxy; confirm no path stripping). From the VM: `curl -k -s -X POST https://82-70-42-188.sslip.io/mcp/<SECRET> ...` same body → same InitializeResult.
- [ ] **Step 6:** Give the operator the exact connector URL `https://82-70-42-188.sslip.io/mcp/<SECRET>` and the setup doc. They add it in Claude.ai (no OAuth) and create the Project (paste `instructions.md`, upload `knowledge.md`).
- [ ] **Step 7:** Live-test from the Project: "what campaigns are active?"; "full config of the income campaign"; "performance by placement for the best creative, last 30 days"; "pause ad set X" (applies); "archive the old test campaigns" (returns preview → confirm). Confirm reads are live and destructive edits previewed.

---

## Verification

- Backend: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q` (existing + `test_mcp_server.py` pass).
- Endpoint: MCP `initialize` returns InitializeResult over localhost and HTTPS.
- Connector: Claude.ai lists the Meta tools after adding the secret URL.
- End-to-end: a deep question ("cheapest age band on the income campaign last 30 days") returns a live, correct answer; a destructive edit asks before applying; `META_LIVE_WRITES_ENABLED=false` blocks writes.

## Risks

- **FastMCP lifespan mounting** — if the session manager lifespan isn't run, the MCP endpoint 500s. Task 5 Step 2 handles it; verify in Task 7 Step 4.
- **Caddy path handling** — confirm `/mcp/...` isn't stripped/redirected (Task 7 Step 5).
- **Secret-URL exposure** — bearer-in-URL; mitigated by 32-byte token + HTTPS + rotation + write gates. OAuth 2.1+PKCE is the future hardening path.
- **mcp SDK version drift** — pin `mcp>=1.2.0`; if `streamable_http_app()` / `session_manager` API differs, WebFetch the MCP Python SDK README and adjust the mount.

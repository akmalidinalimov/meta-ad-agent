import asyncio
from types import SimpleNamespace

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

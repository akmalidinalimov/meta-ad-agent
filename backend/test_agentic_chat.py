"""Tests for the agentic free-text brain (backend/agentic_chat.py).

Covers the action-policy dispatch (`_run_tool`), pending-approval execution
(`execute_pending`), and the tool-use loop (`agentic_reply`) with the model call
seam (`_create_message`) monkeypatched so no network round-trip happens.
"""

from __future__ import annotations

import asyncio

import backend.agentic_chat as agentic_chat


def _run(coro):
    return asyncio.run(coro)


# --- _run_tool: set_status ----------------------------------------------------


def test_set_status_paused_executes_immediately(monkeypatch):
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "c1", "name": "Income VSL"}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)

    calls = []
    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_campaign", _make_async(lambda cfg, cid, payload: calls.append((cid, payload))))
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: object())

    result = _run(agentic_chat._run_tool("set_status", {"level": "campaign", "id": "c1", "status": "PAUSED"}, operator_key="tg:1"))

    assert result["ok"] is True
    assert result["status"] == "PAUSED"
    assert calls == [("c1", {"status": "PAUSED"})]


def test_set_status_active_needs_approval_and_sets_pending(monkeypatch):
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "c1", "name": "Income VSL"}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)

    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_campaign", _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write on ACTIVE"))))
    monkeypatch.setattr(meta_client, "update_ad_set", _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write on ACTIVE"))))

    pendings = []
    from backend import pending_context_store
    monkeypatch.setattr(pending_context_store, "set_pending", lambda op_key, pointer, **kw: pendings.append((op_key, pointer)))

    result = _run(agentic_chat._run_tool("set_status", {"level": "campaign", "id": "c1", "status": "ACTIVE"}, operator_key="tg:1"))

    assert result["needsApproval"] is True
    assert "Activate" in result["proposal"]
    assert pendings and pendings[0][1]["action"] == "set_status"
    assert pendings[0][1]["status"] == "ACTIVE"
    assert pendings[0][1]["kind"] == "agentic"


def test_set_status_live_writes_disabled_returns_error(monkeypatch):
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "c1", "name": "X"}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: False)

    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_campaign", _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("no write when disabled"))))

    result = _run(agentic_chat._run_tool("set_status", {"level": "campaign", "id": "c1", "status": "PAUSED"}, operator_key="tg:1"))

    assert result["ok"] is False
    assert result["error"] == "live writes disabled"


# --- _run_tool: set_budget ----------------------------------------------------


def test_set_budget_decrease_executes(monkeypatch):
    # current = $100/day; new $80 is a decrease -> applies immediately.
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "a1", "name": "AdSet", "daily_budget": 10000}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)

    calls = []
    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_ad_set", _make_async(lambda cfg, aid, payload: calls.append((aid, payload))))
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: object())

    result = _run(agentic_chat._run_tool("set_budget", {"adset_id": "a1", "daily_budget_usd": 80}, operator_key="tg:1"))

    assert result["ok"] is True
    assert calls == [("a1", {"daily_budget": 8000})]


def test_set_budget_within_25_executes(monkeypatch):
    # current = $100/day; new $120 is +20% (within 25%) -> applies.
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "a1", "name": "AdSet", "daily_budget": 10000}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)

    calls = []
    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_ad_set", _make_async(lambda cfg, aid, payload: calls.append((aid, payload))))
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: object())

    result = _run(agentic_chat._run_tool("set_budget", {"adset_id": "a1", "daily_budget_usd": 120}, operator_key="tg:1"))

    assert result["ok"] is True
    assert calls == [("a1", {"daily_budget": 12000})]


def test_set_budget_increase_over_25_needs_approval(monkeypatch):
    # current = $100/day; new $200 is +100% -> needs approval, no write.
    monkeypatch.setattr(agentic_chat, "_find_entity", _make_async(lambda level, eid: {"id": "a1", "name": "AdSet", "daily_budget": 10000}))
    from backend import config as config_mod
    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)

    from backend import meta_client
    monkeypatch.setattr(meta_client, "update_ad_set", _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write on big increase"))))

    pendings = []
    from backend import pending_context_store
    monkeypatch.setattr(pending_context_store, "set_pending", lambda op_key, pointer, **kw: pendings.append((op_key, pointer)))

    result = _run(agentic_chat._run_tool("set_budget", {"adset_id": "a1", "daily_budget_usd": 200}, operator_key="tg:1"))

    assert result["needsApproval"] is True
    assert pendings and pendings[0][1]["action"] == "set_budget"
    assert pendings[0][1]["new_usd"] == 200.0


# --- _run_tool: create_test_campaign -----------------------------------------


def test_create_test_campaign_needs_approval_with_pending(monkeypatch):
    from backend import opportunity_finder, approval_store, meta_client, knowledge_base, playbook_store, pending_context_store

    monkeypatch.setattr(knowledge_base, "load_knowledge_base", lambda: {"analysis": {}})
    monkeypatch.setattr(playbook_store, "load_playbooks", lambda: [])
    monkeypatch.setattr(
        meta_client, "get_meta_config",
        lambda: type("Cfg", (), {"ad_account_id": "act_1", "pixel_id": "px_1"})(),
    )

    fake_approval = {"title": "AI Test", "after": {"name": "AI Test - DRAFT", "adsets": [{"name": "Income - DRAFT", "daily_budget": 10000}]}}
    monkeypatch.setattr(opportunity_finder, "build_autonomous_campaign", lambda *a, **k: fake_approval)
    monkeypatch.setattr(approval_store, "create_approval_request", lambda approval: {**approval, "id": "appr_99"})

    pendings = []
    monkeypatch.setattr(pending_context_store, "set_pending", lambda op_key, pointer, **kw: pendings.append((op_key, pointer)))

    result = _run(agentic_chat._run_tool("create_test_campaign", {}, operator_key="tg:1"))

    assert result["needsApproval"] is True
    assert "reply approve" in result["proposal"].lower()
    assert pendings and pendings[0][1]["action"] == "create"
    assert pendings[0][1]["approvalId"] == "appr_99"


def test_create_test_campaign_no_audiences_returns_error(monkeypatch):
    from backend import opportunity_finder, meta_client, knowledge_base, playbook_store

    monkeypatch.setattr(knowledge_base, "load_knowledge_base", lambda: {})
    monkeypatch.setattr(playbook_store, "load_playbooks", lambda: [])
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: type("Cfg", (), {"ad_account_id": "", "pixel_id": ""})())
    monkeypatch.setattr(opportunity_finder, "build_autonomous_campaign", lambda *a, **k: None)

    result = _run(agentic_chat._run_tool("create_test_campaign", {}, operator_key="tg:1"))

    assert result["ok"] is False
    assert result["error"] == "no usable audience data"


# --- execute_pending ----------------------------------------------------------


def test_execute_pending_set_status_active_writes_active(monkeypatch):
    from backend import config as config_mod, meta_client

    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(meta_client, "update_campaign", _make_async(lambda cfg, cid, payload: calls.append((cid, payload))))
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: object())

    pending = {"action": "set_status", "level": "campaign", "id": "c1", "status": "ACTIVE", "label": "Income VSL"}
    msg = agentic_chat.execute_pending(pending, "tg:1")

    assert calls == [("c1", {"status": "ACTIVE"})]
    assert "Activated" in msg


def test_execute_pending_create_calls_auto_execute(monkeypatch):
    from backend import config as config_mod, execution_service

    monkeypatch.setattr(config_mod, "live_writes_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(execution_service, "auto_execute_paused", lambda aid: calls.append(aid) or {"ok": True})

    pending = {"action": "create", "approvalId": "appr_5", "label": "AI Test"}
    msg = agentic_chat.execute_pending(pending, "tg:1")

    assert calls == ["appr_5"]
    assert "Created PAUSED" in msg


# --- agentic_reply tool loop --------------------------------------------------


class _Block:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


def test_agentic_reply_runs_tool_then_returns_final_text(monkeypatch):
    # First model turn asks to use list_campaigns; second returns final prose.
    turns = iter([
        _Resp(
            [_Block("tool_use", id="tu1", name="list_campaigns", input={"status": "ACTIVE"})],
            "tool_use",
        ),
        _Resp([_Block("text", text="You have 2 active campaigns.")], "end_turn"),
    ])

    async def fake_create(client, **kwargs):
        return next(turns)

    monkeypatch.setattr(agentic_chat, "_create_message", fake_create)
    monkeypatch.setattr(agentic_chat, "_build_client", lambda: object())

    dispatched = []

    async def fake_run_tool(name, args, *, operator_key):
        dispatched.append((name, args, operator_key))
        return {"count": 2}

    monkeypatch.setattr(agentic_chat, "_run_tool", fake_run_tool)

    answer = asyncio.run(agentic_chat.agentic_reply("what's active?", operator_key="tg:1"))

    assert answer == "You have 2 active campaigns."
    assert dispatched == [("list_campaigns", {"status": "ACTIVE"}, "tg:1")]


def test_agentic_reply_answers_directly_without_tools(monkeypatch):
    async def fake_create(client, **kwargs):
        return _Resp([_Block("text", text="A good CTR here is ~1.5-3%.")], "end_turn")

    monkeypatch.setattr(agentic_chat, "_create_message", fake_create)
    monkeypatch.setattr(agentic_chat, "_build_client", lambda: object())
    monkeypatch.setattr(agentic_chat, "_run_tool", _make_async(lambda *a, **k: (_ for _ in ()).throw(AssertionError("no tool needed"))))

    answer = asyncio.run(agentic_chat.agentic_reply("what's a good CTR?", operator_key="tg:1"))

    assert "CTR" in answer


# --- helpers ------------------------------------------------------------------


def _make_async(fn):
    async def _wrapped(*args, **kwargs):
        return fn(*args, **kwargs)

    return _wrapped

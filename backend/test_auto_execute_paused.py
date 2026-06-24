"""Tests for execution_service.auto_execute_paused — the no-tap auto-create-to-PAUSED
path shared by the web chat and Telegram autonomous builds."""

from __future__ import annotations

import backend.approval_store as approval_store
import backend.config as config
import backend.execution_service as execution_service
import backend.meta_client as meta_client


def _paused_approval(approval_id="autonomous_1", guardrail="pass"):
    return {
        "id": approval_id,
        "actionType": "create_paused_campaign_structure",
        "status": "needs_review",
        "guardrailResult": guardrail,
        "after": {
            "campaign": {"name": "Best Guess - DRAFT", "status": "PAUSED"},
            "adsets": [
                {
                    "name": "AI - DRAFT",
                    "status": "PAUSED",
                    "daily_budget": 10000,
                    "ads": [{"name": "Winner - AI", "creativeId": "cr_1", "status": "PAUSED"}],
                }
            ],
        },
    }


def _wire(monkeypatch, *, approval, live_writes, calls):
    rows = {approval["id"]: dict(approval)}

    monkeypatch.setattr(approval_store, "list_approval_requests", lambda **kw: list(rows.values()))

    def fake_approve(approval_id, *, approved_by, **kw):
        rows[approval_id]["status"] = "approved"
        rows[approval_id]["approvedBy"] = approved_by
        return dict(rows[approval_id])

    monkeypatch.setattr(approval_store, "approve_request", fake_approve)

    def fake_update(approval_id, patch, **kw):
        rows[approval_id].update(patch)
        return dict(rows[approval_id])

    monkeypatch.setattr(approval_store, "update_approval_request", fake_update)
    monkeypatch.setattr(config, "live_writes_enabled", lambda: live_writes)
    monkeypatch.setattr(meta_client, "get_meta_config", lambda: object())

    async def create_campaign(c, payload):
        calls.append(("campaign", payload))
        return {"id": "cmp_live_1"}

    async def create_ad_set(c, payload):
        calls.append(("adset", payload))
        return {"id": "as_live_1"}

    async def create_ad(c, payload):
        calls.append(("ad", payload))
        return {"id": "ad_live_1"}

    monkeypatch.setattr(meta_client, "create_campaign", create_campaign)
    monkeypatch.setattr(meta_client, "create_ad_set", create_ad_set)
    monkeypatch.setattr(meta_client, "create_ad", create_ad)
    return rows


def test_auto_execute_paused_creates_objects_when_gate_passes(monkeypatch):
    calls: list = []
    rows = _wire(monkeypatch, approval=_paused_approval(), live_writes=True, calls=calls)

    result = execution_service.auto_execute_paused("autonomous_1")

    assert result["ok"] is True
    assert result["blocked"] is None
    levels = [obj["level"] for obj in result["created"]]
    assert levels == ["campaign", "adset", "ad"]
    # All three create fns were called (campaign + ad set + ad).
    assert [c[0] for c in calls] == ["campaign", "adset", "ad"]
    # The packet was approved by the autonomous agent and marked executed.
    assert rows["autonomous_1"]["status"] == "executed"
    assert rows["autonomous_1"]["approvedBy"] == "agent:autonomous"


def test_auto_execute_paused_refuses_when_live_writes_disabled(monkeypatch):
    calls: list = []
    rows = _wire(monkeypatch, approval=_paused_approval(), live_writes=False, calls=calls)

    result = execution_service.auto_execute_paused("autonomous_1")

    assert result["ok"] is False
    assert "disabled" in result["blocked"].lower()
    # No Meta writes happened and the packet stays needs_review (never approved).
    assert calls == []
    assert rows["autonomous_1"]["status"] == "needs_review"


def test_auto_execute_paused_refuses_on_guardrail_fail(monkeypatch):
    calls: list = []
    rows = _wire(
        monkeypatch,
        approval=_paused_approval(guardrail="fail"),
        live_writes=True,
        calls=calls,
    )

    result = execution_service.auto_execute_paused("autonomous_1")

    assert result["ok"] is False
    assert "guardrail" in result["blocked"].lower()
    assert calls == []
    assert rows["autonomous_1"]["status"] == "needs_review"

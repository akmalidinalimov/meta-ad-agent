import asyncio

from fastapi.testclient import TestClient

import backend.approval_store as approval_store
import backend.routers.approvals as approvals_module
from backend.app import app
from backend.approval_store import create_approval_request, list_approval_requests
from backend.meta_execution import execute_manage_campaigns_approval
from backend.test_approval_execution_api import FakeMetaActionWriter, bind_tmp_execution_store


class FakeMetaWriter:
    def __init__(self, *, fail_ids=None):
        self.calls = []
        self.fail_ids = set(fail_ids or [])

    async def update_campaign(self, object_id, payload):
        self.calls.append(("campaign", object_id, payload))
        if object_id in self.fail_ids:
            raise RuntimeError("Meta rejected the write")
        return {"success": True, "id": object_id, **payload}


def _approval(status="approved", status_value="ARCHIVED", campaigns=None):
    return {
        "id": "approval_manage",
        "status": status,
        "actionType": "manage_campaigns",
        "target": {"level": "campaign_set", "id": "act_1", "name": "2 campaigns"},
        "after": {
            "status": status_value,
            "campaigns": campaigns
            or [
                {"id": "cmp_a", "name": "A", "effective_status": "PAUSED"},
                {"id": "cmp_b", "name": "B", "effective_status": "PAUSED"},
            ],
        },
    }


def test_execute_manage_updates_each_campaign_status():
    writer = FakeMetaWriter()
    result = asyncio.run(execute_manage_campaigns_approval(_approval(), writer=writer))

    assert result["ok"] is True
    assert {c["id"] for c in result["changed"]} == {"cmp_a", "cmp_b"}
    assert all(c["status"] == "ARCHIVED" for c in result["changed"])
    assert writer.calls == [
        ("campaign", "cmp_a", {"status": "ARCHIVED"}),
        ("campaign", "cmp_b", {"status": "ARCHIVED"}),
    ]


def test_execute_manage_pause_status():
    writer = FakeMetaWriter()
    result = asyncio.run(
        execute_manage_campaigns_approval(_approval(status_value="PAUSED"), writer=writer)
    )
    assert all(c["status"] == "PAUSED" for c in result["changed"])
    assert writer.calls[0][2] == {"status": "PAUSED"}


def test_execute_manage_tolerates_per_item_failure():
    writer = FakeMetaWriter(fail_ids={"cmp_a"})
    result = asyncio.run(execute_manage_campaigns_approval(_approval(), writer=writer))

    assert result["ok"] is True
    assert {c["id"] for c in result["changed"]} == {"cmp_b"}
    assert result["errors"] and result["errors"][0]["id"] == "cmp_a"


def test_execute_manage_rejects_unapproved():
    writer = FakeMetaWriter()
    result = asyncio.run(
        execute_manage_campaigns_approval(_approval(status="needs_review"), writer=writer)
    )
    assert result["ok"] is False
    assert "approved" in result["blockedReason"].lower()
    assert writer.calls == []


def _manage_approval_record(status="approved"):
    return {
        "id": "approval_manage_api",
        "status": status,
        "actionType": "manage_campaigns",
        "target": {"level": "campaign_set", "id": "act_1", "name": "2 campaigns"},
        "before": {},
        "after": {
            "status": "ARCHIVED",
            "campaigns": [
                {"id": "cmp_a", "name": "A", "effective_status": "PAUSED"},
                {"id": "cmp_b", "name": "B", "effective_status": "PAUSED"},
            ],
        },
        "risk": "medium",
        "guardrailResult": "pass",
        "guardrailChecks": [{"result": "info", "message": "2 selected."}],
        "executionMethod": "api",
        "requiresApproval": True,
    }


def test_manage_dry_run_returns_would_change_without_writing(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setattr(approvals_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(_manage_approval_record(), storage_dir=storage_dir)
    client = TestClient(app)

    response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": True, "confirmLive": False},
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["dryRun"] is True
    assert {c["id"] for c in result["wouldChange"]} == {"cmp_a", "cmp_b"}
    assert result["status"] == "ARCHIVED"
    assert writer.calls == []


def test_manage_live_execution_sets_status_via_writer(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(approvals_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(_manage_approval_record(), storage_dir=storage_dir)
    client = TestClient(app)

    response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": False, "confirmLive": True},
    )

    assert response.status_code == 200
    assert response.json()["result"]["ok"] is True
    assert writer.calls == [
        ("campaign", "cmp_a", {"status": "ARCHIVED"}),
        ("campaign", "cmp_b", {"status": "ARCHIVED"}),
    ]


def test_manage_live_execution_blocked_without_confirm_live(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(approvals_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(_manage_approval_record(), storage_dir=storage_dir)
    client = TestClient(app)

    response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": False, "confirmLive": False},
    )

    assert response.status_code == 400
    assert writer.calls == []

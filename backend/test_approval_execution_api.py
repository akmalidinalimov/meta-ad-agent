from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task, update_agent_task_by_approval
from backend.app import app
from backend.approval_store import approve_request, create_approval_request, list_approval_requests, update_approval_request


class FakeMetaActionWriter:
    def __init__(self):
        self.calls = []

    async def update_campaign(self, object_id, payload):
        self.calls.append(("campaign", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad_set(self, object_id, payload):
        self.calls.append(("adset", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad(self, object_id, payload):
        self.calls.append(("ad", object_id, payload))
        return {"success": True, "id": object_id, **payload}


def bind_tmp_execution_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(app_module, "create_agent_task", lambda task: create_agent_task(task, storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(
        app_module,
        "update_agent_task",
        lambda task_id, patch: update_agent_task(task_id, patch, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        app_module,
        "create_approval_request",
        lambda request: create_approval_request(request, storage_dir=storage_dir),
    )
    monkeypatch.setattr(app_module, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(
        app_module,
        "update_approval_request",
        lambda approval_id, patch: update_approval_request(approval_id, patch, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        app_module,
        "approve_request",
        lambda approval_id, *, approved_by: approve_request(approval_id, approved_by=approved_by, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        app_module,
        "update_agent_task_by_approval",
        lambda approval_id, patch: update_agent_task_by_approval(approval_id, patch, storage_dir=storage_dir),
    )
    return storage_dir


def approved_rename_request() -> dict:
    return {
        "id": "approval_rename_api",
        "status": "approved",
        "actionType": "rename_meta_object",
        "target": {"level": "campaign", "id": "120123", "name": "120123"},
        "before": {"name": "Old Name"},
        "after": {"name": "Business Automation VSL - Tashkent"},
        "risk": "low",
        "guardrailResult": "pass",
        "guardrailChecks": [{"result": "pass", "message": "Human approval recorded."}],
        "executionMethod": "api",
        "requiresApproval": True,
    }


def test_execute_approved_rename_action_updates_approval_with_result(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(app_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(approved_rename_request(), storage_dir=storage_dir)
    create_agent_task(
        {
            "id": "task_rename",
            "source": "telegram",
            "command": "Rename campaign 120123 to Business Automation VSL - Tashkent",
            "status": "approved",
            "approvalId": saved["id"],
        },
        storage_dir=storage_dir,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": False, "confirmLive": True},
    )

    payload = response.json()
    approvals = list_approval_requests(storage_dir=storage_dir)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["approval"]["status"] == "executed"
    assert approvals[0]["lastExecutionResult"]["ok"] is True
    assert writer.calls == [("campaign", "120123", {"name": "Business Automation VSL - Tashkent"})]
    assert payload["task"]["status"] == "executed"


def test_dry_run_approved_rename_action_does_not_call_meta(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setattr(app_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(approved_rename_request(), storage_dir=storage_dir)
    client = TestClient(app)

    response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": True, "confirmLive": False},
    )

    assert response.status_code == 200
    assert response.json()["result"]["dryRun"] is True
    assert response.json()["result"]["wouldUpdate"] == {
        "target": {"level": "campaign", "id": "120123", "name": "120123"},
        "payload": {"name": "Business Automation VSL - Tashkent"},
    }
    assert writer.calls == []


def test_live_execution_can_follow_successful_dry_run(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(app_module, "build_meta_action_writer", lambda config: writer)
    saved = create_approval_request(approved_rename_request(), storage_dir=storage_dir)
    client = TestClient(app)

    dry_run_response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": True, "confirmLive": False},
    )
    live_response = client.post(
        f"/api/approvals/{saved['id']}/execute",
        json={"dryRun": False, "confirmLive": True},
    )

    assert dry_run_response.status_code == 200
    assert dry_run_response.json()["approval"]["status"] == "dry_run_completed"
    assert live_response.status_code == 200
    assert live_response.json()["approval"]["status"] == "executed"
    assert writer.calls == [("campaign", "120123", {"name": "Business Automation VSL - Tashkent"})]


def test_end_to_end_natural_language_action_approval_dry_run_and_live_execution(monkeypatch, tmp_path):
    storage_dir = bind_tmp_execution_store(monkeypatch, tmp_path)
    writer = FakeMetaActionWriter()
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(app_module, "build_meta_action_writer", lambda config: writer)
    monkeypatch.setattr(app_module, "send_approval_notification", lambda approval: {"ok": True, "approvalId": approval["id"]})
    client = TestClient(app)

    task_response = client.post(
        "/api/tasks",
        json={
            "source": "dashboard",
            "command": "Rename campaign 120123 to Business Automation VSL - Tashkent",
        },
    )
    approval_id = task_response.json()["task"]["approvalId"]
    approve_response = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"approvedBy": "akmal"},
    )
    dry_run_response = client.post(
        f"/api/approvals/{approval_id}/execute",
        json={"dryRun": True, "confirmLive": False},
    )
    live_response = client.post(
        f"/api/approvals/{approval_id}/execute",
        json={"dryRun": False, "confirmLive": True},
    )
    tasks = list_agent_tasks(storage_dir=storage_dir)

    assert task_response.status_code == 200
    assert task_response.json()["task"]["status"] == "needs_approval"
    assert approve_response.status_code == 200
    assert dry_run_response.status_code == 200
    assert live_response.status_code == 200
    assert live_response.json()["approval"]["status"] == "executed"
    assert tasks[0]["status"] == "executed"
    assert writer.calls == [("campaign", "120123", {"name": "Business Automation VSL - Tashkent"})]

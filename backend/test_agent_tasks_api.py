from fastapi.testclient import TestClient

import backend.app as app_module
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task
from backend.app import app
from backend.approval_store import create_approval_request, list_approval_requests


def bind_tmp_task_and_approval_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(
        app_module,
        "create_agent_task",
        lambda task: create_agent_task(task, storage_dir=storage_dir),
    )
    monkeypatch.setattr(
        app_module,
        "list_agent_tasks",
        lambda: list_agent_tasks(storage_dir=storage_dir),
    )
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
    monkeypatch.setattr(
        app_module,
        "list_approval_requests",
        lambda: list_approval_requests(storage_dir=storage_dir),
    )


def test_create_agent_task_from_dashboard_command(monkeypatch, tmp_path):
    bind_tmp_task_and_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={
            "source": "dashboard",
            "command": "Create a campaign with 3 VSLs: income, business automation, creators. Use $100 each.",
            "campaignGroupId": "june-launch",
            "segmentIds": ["income", "business", "creators"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["task"]["status"] == "planning"
    assert payload["task"]["source"] == "dashboard"
    assert payload["task"]["activeAgent"] == "orchestrator"
    assert "generatedPlaybook" in payload["task"]["plan"]


def test_create_agent_task_can_prepare_campaign_approval(monkeypatch, tmp_path):
    bind_tmp_task_and_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={
            "source": "telegram",
            "command": "Create a campaign with 1 VSL: business owners. Use $100 each and optimize for Telegram START.",
            "prepareApproval": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    task = payload["task"]
    approvals = client.get("/api/approvals").json()["approvals"]

    assert task["status"] == "needs_approval"
    assert task["approvalId"] == approvals[0]["id"]
    assert approvals[0]["status"] == "needs_review"
    assert approvals[0]["after"]["campaign"]["status"] == "PAUSED"


def test_list_agent_tasks_returns_recent_tasks(monkeypatch, tmp_path):
    bind_tmp_task_and_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/api/tasks", json={"source": "codex", "command": "Prepare a placement test"})

    response = client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["source"] == "codex"

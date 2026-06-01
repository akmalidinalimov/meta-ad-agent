from fastapi.testclient import TestClient

import backend.agent_task_store as agent_task_store
import backend.approval_store as approval_store
import backend.telegram_outbound as telegram_outbound
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task
from backend.app import app
import backend.task_service as task_service_mod
import backend.routers.approvals as approvals_router_mod
import backend.routers.tasks as tasks_router_mod
import backend.telegram_service as telegram_service_mod
from backend.approval_store import create_approval_request, list_approval_requests


def bind_tmp_task_and_approval_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(
        agent_task_store,
        "create_agent_task",
        lambda task: create_agent_task(task, storage_dir=storage_dir),
    )
    monkeypatch.setattr(tasks_router_mod, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(telegram_service_mod, "list_agent_tasks", lambda: list_agent_tasks(storage_dir=storage_dir))
    monkeypatch.setattr(task_service_mod, "update_agent_task", lambda task_id, patch: update_agent_task(task_id, patch, storage_dir=storage_dir))
    monkeypatch.setattr(
        approval_store,
        "create_approval_request",
        lambda request: create_approval_request(request, storage_dir=storage_dir),
    )
    monkeypatch.setattr(approvals_router_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(telegram_service_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(
        telegram_outbound,
        "send_approval_notification",
        lambda approval: {"ok": True, "approvalId": approval["id"]},
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


def test_create_agent_task_from_natural_language_meta_action_creates_approval(monkeypatch, tmp_path):
    bind_tmp_task_and_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/tasks",
        json={
            "source": "telegram",
            "command": "Rename campaign 120123 to Business Automation VSL - Tashkent",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    task = payload["task"]
    approvals = client.get("/api/approvals").json()["approvals"]

    assert task["status"] == "needs_approval"
    assert task["activeAgent"] == "execution"
    assert task["approvalId"] == approvals[0]["id"]
    assert task["plan"]["generatedMetaActionPlan"]["intent"] == "rename"
    assert approvals[0]["actionType"] == "rename_meta_object"
    assert approvals[0]["target"]["id"] == "120123"
    assert approvals[0]["after"]["name"] == "Business Automation VSL - Tashkent"

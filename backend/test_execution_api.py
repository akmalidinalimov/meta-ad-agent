from fastapi.testclient import TestClient

import backend.agent_task_store as agent_task_store
import backend.approval_store as approval_store
from backend.app import app
import backend.routers.approvals as approvals_router_mod
import backend.telegram_service as telegram_service_mod
from backend.agent_task_store import create_agent_task, list_agent_tasks, update_agent_task_by_approval
from backend.approval_store import (
    approve_request,
    create_approval_request,
    list_approval_requests,
    reject_request,
    request_changes,
    update_approval_request,
)


def bind_tmp_approval_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(
        approval_store,
        "create_approval_request",
        lambda request: create_approval_request(request, storage_dir=storage_dir),
    )
    monkeypatch.setattr(approvals_router_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(telegram_service_mod, "list_approval_requests", lambda: list_approval_requests(storage_dir=storage_dir))
    monkeypatch.setattr(
        approval_store,
        "approve_request",
        lambda approval_id, *, approved_by: approve_request(
            approval_id,
            approved_by=approved_by,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        approval_store,
        "update_approval_request",
        lambda approval_id, patch: update_approval_request(
            approval_id,
            patch,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        approval_store,
        "reject_request",
        lambda approval_id, *, rejected_by, reason: reject_request(
            approval_id,
            rejected_by=rejected_by,
            reason=reason,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        approval_store,
        "request_changes",
        lambda approval_id, *, requested_by, note: request_changes(
            approval_id,
            requested_by=requested_by,
            note=note,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        agent_task_store,
        "update_agent_task_by_approval",
        lambda approval_id, patch: update_agent_task_by_approval(approval_id, patch, storage_dir=storage_dir),
    )
    return storage_dir


def test_prepare_campaign_execution_creates_reviewable_approval(monkeypatch, tmp_path):
    bind_tmp_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/execution/prepare-campaign",
        json={
            "playbook": {
                "id": "pb_api",
                "name": "API test launch",
                "primarySuccessMetric": "telegram_start",
                "segments": [
                    {
                        "id": "income",
                        "name": "Income test",
                        "startingBudgetUsd": 100,
                        "locations": ["Uzbekistan"],
                        "placements": ["instagram_reels", "instagram_stories"],
                        "interests": ["Marketing services and organizations"],
                        "ageRange": "23-44",
                    }
                ],
                "rules": {
                    "maxDailyBudgetUsd": 300,
                    "requiresApprovalForExecution": True,
                },
            },
            "reason": "Use top cheap-click audience cluster from the 90-day analysis.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["approval"]["status"] == "needs_review"
    assert payload["approval"]["after"]["campaign"]["status"] == "PAUSED"
    assert payload["approval"]["after"]["adsets"][0]["targeting"]["publisher_platforms"] == ["instagram"]


def test_execute_campaign_approval_dry_run_requires_approval(monkeypatch, tmp_path):
    bind_tmp_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)
    prepared = client.post(
        "/api/execution/prepare-campaign",
        json={
            "playbook": {
                "id": "pb_api_execute",
                "name": "Dry run launch",
                "segments": [
                    {
                        "id": "business",
                        "name": "Business owners",
                        "startingBudgetUsd": 100,
                        "locations": ["Tashkent"],
                        "placements": ["instagram_reels"],
                        "interests": ["Online advertising"],
                    }
                ],
                "rules": {"maxDailyBudgetUsd": 300},
            }
        },
    ).json()
    approval_id = prepared["approval"]["id"]

    blocked = client.post(f"/api/approvals/{approval_id}/execute", json={"dryRun": True})
    assert blocked.status_code == 400

    approved = client.post(f"/api/approvals/{approval_id}/approve", json={"approvedBy": "test"})
    assert approved.status_code == 200

    executed = client.post(f"/api/approvals/{approval_id}/execute", json={"dryRun": True})
    assert executed.status_code == 200
    payload = executed.json()
    assert payload["result"]["ok"] is True
    assert payload["result"]["dryRun"] is True
    assert payload["result"]["created"] == []


def test_execute_campaign_approval_blocks_live_when_env_is_disabled(monkeypatch, tmp_path):
    bind_tmp_approval_store(monkeypatch, tmp_path)
    monkeypatch.delenv("META_LIVE_WRITES_ENABLED", raising=False)
    client = TestClient(app)
    prepared = client.post(
        "/api/execution/prepare-campaign",
        json={
            "playbook": {
                "id": "pb_api_live_block",
                "name": "Live blocked launch",
                "segments": [
                    {
                        "id": "income",
                        "name": "Income seekers",
                        "startingBudgetUsd": 100,
                        "locations": ["Uzbekistan"],
                        "placements": ["instagram_reels"],
                        "interests": ["Marketing services and organizations"],
                    }
                ],
                "rules": {"maxDailyBudgetUsd": 300},
            }
        },
    ).json()
    approval_id = prepared["approval"]["id"]

    approved = client.post(f"/api/approvals/{approval_id}/approve", json={"approvedBy": "test"})
    assert approved.status_code == 200

    blocked = client.post(
        f"/api/approvals/{approval_id}/execute",
        json={"dryRun": False, "confirmLive": True},
    )

    assert blocked.status_code == 400
    assert "disabled" in blocked.json()["detail"].lower()


def test_approval_reject_and_changes_endpoints_update_status(monkeypatch, tmp_path):
    storage_dir = bind_tmp_approval_store(monkeypatch, tmp_path)
    client = TestClient(app)
    prepared = client.post(
        "/api/execution/prepare-campaign",
        json={
            "playbook": {
                "id": "pb_decisions",
                "name": "Decision launch",
                "segments": [{"id": "income", "name": "Income", "startingBudgetUsd": 50}],
                "rules": {"maxDailyBudgetUsd": 100},
            }
        },
    ).json()
    approval_id = prepared["approval"]["id"]
    create_agent_task(
        {
            "source": "dashboard",
            "command": "Prepare approval",
            "status": "needs_approval",
            "approvalId": approval_id,
        },
        storage_dir=storage_dir,
    )

    changes = client.post(
        f"/api/approvals/{approval_id}/changes",
        json={"requestedBy": "dashboard", "note": "Use Tashkent only as challenger."},
    )
    assert changes.status_code == 200
    assert changes.json()["approval"]["status"] == "needs_changes"
    assert list_agent_tasks(storage_dir=storage_dir)[0]["status"] == "needs_changes"

    rejected = client.post(
        f"/api/approvals/{approval_id}/reject",
        json={"rejectedBy": "dashboard", "reason": "Budget not approved."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval"]["status"] == "rejected"
    assert list_agent_tasks(storage_dir=storage_dir)[0]["status"] == "rejected"

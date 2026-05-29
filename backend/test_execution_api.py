from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app
from backend.approval_store import (
    approve_request,
    create_approval_request,
    list_approval_requests,
    update_approval_request,
)


def bind_tmp_approval_store(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
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
    monkeypatch.setattr(
        app_module,
        "approve_request",
        lambda approval_id, *, approved_by: approve_request(
            approval_id,
            approved_by=approved_by,
            storage_dir=storage_dir,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "update_approval_request",
        lambda approval_id, patch: update_approval_request(
            approval_id,
            patch,
            storage_dir=storage_dir,
        ),
    )


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

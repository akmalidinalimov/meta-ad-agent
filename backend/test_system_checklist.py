from fastapi.testclient import TestClient

from backend.app import app
from backend.system_checklist import build_system_checklist


def test_build_system_checklist_covers_completion_tasks():
    checklist = build_system_checklist(
        agents=[{"id": "orchestrator"}, {"id": "execution"}],
        knowledge={"analysis": {"summary": {"spend": 100}, "rawCounts": {"campaigns": 2}}},
        approvals=[{"id": "approval_1", "status": "needs_review"}],
        monitoring_runs=[{"status": "completed"}],
    )

    ids = {item["id"] for item in checklist["items"]}
    assert "launch_packet" in ids
    assert "approval_workflow" in ids
    assert "agent_capability_harness" in ids
    assert "regression_checklist" in ids
    assert checklist["summary"]["total"] >= 10
    assert checklist["summary"]["ready"] > 0


def test_system_checklist_endpoint_returns_statuses():
    client = TestClient(app)

    response = client.get("/api/system/checklist")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert payload["summary"]["total"] >= 10


def test_agents_endpoint_exposes_readiness_status():
    client = TestClient(app)

    response = client.get("/api/agents")

    assert response.status_code == 200
    agents = response.json()["agents"]
    execution = next(agent for agent in agents if agent["id"] == "execution")
    assert execution["readinessStatus"] in {"blocked", "ready", "needs_data"}
    assert "lastVerifiedBy" in execution
    assert "blockedReasons" in execution

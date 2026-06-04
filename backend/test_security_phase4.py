from fastapi.testclient import TestClient

import backend.routers.approvals as approvals_module
from backend.app import app
from backend.meta_action_planner import plan_meta_action
from backend.meta_execution import assert_executable


client = TestClient(app)


def test_jsonp_dashboard_disabled_by_default():
    response = client.get("/api/dashboard.js")
    assert response.status_code == 404


def test_jsonp_dashboard_served_when_enabled(monkeypatch):
    monkeypatch.setenv("DASHBOARD_JSONP_ENABLED", "true")
    response = client.get("/api/dashboard.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")


def test_state_changing_route_requires_api_key_when_configured(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEY", "secret-key")
    # No header -> rejected.
    denied = client.post("/api/approvals/x/approve", json={"approvedBy": "tester"})
    assert denied.status_code == 401
    # Wrong key -> rejected.
    wrong = client.post("/api/approvals/x/approve", json={"approvedBy": "tester"}, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


def test_auth_disabled_when_no_key_configured(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    # Auth off: request passes the dependency and reaches the handler (404 for a
    # missing approval, NOT 401).
    response = client.post("/api/approvals/does-not-exist/approve", json={"approvedBy": "tester"})
    assert response.status_code == 404


def test_assert_executable_unified_gate():
    approved = {"status": "approved", "guardrailResult": "pass"}
    assert assert_executable(approved, confirm_live=True, live_writes_enabled=True) is None
    assert "confirmation" in assert_executable(approved, confirm_live=False, live_writes_enabled=True)
    assert "disabled" in assert_executable(approved, confirm_live=True, live_writes_enabled=False)
    blocked = {"status": "needs_review", "guardrailResult": "pass"}
    assert "approval" in assert_executable(blocked, confirm_live=True, live_writes_enabled=True).lower()


def test_idempotent_live_execute_returns_prior_result(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    # An approval already executed once under clientRequestId "abc".
    prior = {"ok": True, "created": [{"level": "campaign", "id": "111"}]}
    approval = {
        "id": "ap1",
        "actionType": "create_paused_campaign_structure",
        "status": "executed",
        "guardrailResult": "pass",
        "executionLog": [{"clientRequestId": "abc", "dryRun": False, "result": prior}],
    }
    monkeypatch.setattr(approvals_module, "list_approval_requests", lambda: [approval])
    monkeypatch.setenv("META_LIVE_WRITES_ENABLED", "true")

    response = client.post(
        "/api/approvals/ap1/execute",
        json={"dryRun": False, "confirmLive": True, "clientRequestId": "abc"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["idempotent"] is True
    assert payload["result"] == prior


def test_parser_flags_bare_number_target_as_ambiguous():
    ambiguous = plan_meta_action("pause 12345678")
    assert ambiguous["needsClarification"] is True
    assert "bare number" in (ambiguous["clarifyingQuestion"] or "")

    explicit = plan_meta_action("pause campaign 12345678")
    assert explicit["needsClarification"] is False

"""Agent status feed — session-guarded, viewer-readable."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("DASHBOARD_SESSION_AUTH", "true")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    from backend import members_store

    importlib.reload(members_store)
    members_store.list_members()  # seed owner from TELEGRAM_ADMIN_CHAT_ID
    members_store.add_member(user_id="100", role="viewer", added_by="42")

    from backend import agent_activity

    agent_activity.reset_live_for_tests()

    from backend import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def _cookie(sub):
    from backend.webapp_auth import make_session

    return {"session": make_session(sub)}


def test_unauthenticated_gets_401(client):
    assert client.get("/api/agents/status").status_code == 401


def test_viewer_can_read_status(client):
    resp = client.get("/api/agents/status", cookies=_cookie("tg:100"))
    assert resp.status_code == 200
    payload = resp.json()
    assert [agent["id"] for agent in payload["agents"]] == [
        "monitor",
        "analyst",
        "planner",
        "creative",
    ]
    assert "events" in payload
    assert payload["updatedAt"]


def test_working_agent_is_reported_with_activity(client):
    from backend import agent_activity

    agent_activity.begin("monitor", "scanning ad sets")
    try:
        resp = client.get("/api/agents/status", cookies=_cookie("admin"))
        monitor = next(a for a in resp.json()["agents"] if a["id"] == "monitor")
        assert monitor["state"] == "working"
        assert monitor["activity"] == "scanning ad sets"
        assert monitor["sinceSeconds"] >= 0
    finally:
        agent_activity.end("monitor")  # no summary: nothing persisted


def test_idle_agent_has_no_activity(client):
    resp = client.get("/api/agents/status", cookies=_cookie("admin"))
    analyst = next(a for a in resp.json()["agents"] if a["id"] == "analyst")
    assert analyst["state"] in ("idle", "scheduled")
    assert analyst["activity"] is None


def test_scheduled_agent_reports_future_next_run(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.routers import agent_status

    finished = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    monkeypatch.setattr(
        agent_status,
        "list_monitoring_runs",
        lambda: [{"status": "completed", "finishedAt": finished}],
    )
    resp = client.get("/api/agents/status", cookies=_cookie("admin"))
    monitor = next(a for a in resp.json()["agents"] if a["id"] == "monitor")
    assert monitor["state"] == "scheduled"
    assert monitor["nextRunAt"] is not None  # finished 2h ago + 4h interval = 2h from now


def test_stale_next_run_degrades_to_idle(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.routers import agent_status

    finished = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    monkeypatch.setattr(
        agent_status,
        "list_monitoring_runs",
        lambda: [{"status": "completed", "finishedAt": finished}],
    )
    resp = client.get("/api/agents/status", cookies=_cookie("admin"))
    monitor = next(a for a in resp.json()["agents"] if a["id"] == "monitor")
    assert monitor["state"] == "idle"
    assert monitor["nextRunAt"] is None

"""Session role wiring + viewer read-only mutation guard."""

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
    members_store.list_members()  # seed owner
    members_store.add_member(user_id="100", role="viewer", added_by="42")
    members_store.add_member(user_id="200", role="admin", added_by="42")

    from backend import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def _cookie(sub):
    from backend.webapp_auth import make_session

    return {"session": make_session(sub)}


def test_session_status_returns_owner_role(client):
    resp = client.get("/api/auth/session", cookies=_cookie("admin"))
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"


def test_viewer_blocked_from_mutation(client):
    resp = client.post("/api/meta/sync", json={}, cookies=_cookie("tg:100"))
    assert resp.status_code == 403


def test_admin_passes_mutation_guard(client):
    # The admin has the "act" capability, so the guard must NOT 403. The endpoint
    # may still fail downstream (404/422/500) — we only assert it's not 403.
    resp = client.post("/api/meta/sync", json={}, cookies=_cookie("tg:200"))
    assert resp.status_code != 403

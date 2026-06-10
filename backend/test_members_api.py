"""Web members CRUD API — manager-gated, owner-protected."""

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
    # Seed the owner plus a viewer (tg:100) and an admin (tg:200).
    members_store.list_members()  # triggers owner seed from TELEGRAM_ADMIN_CHAT_ID
    members_store.add_member(user_id="100", role="viewer", added_by="42")
    members_store.add_member(user_id="200", role="admin", added_by="42")

    from backend import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def _cookie(sub):
    from backend.webapp_auth import make_session

    return {"session": make_session(sub)}


def test_owner_lists_members(client):
    resp = client.get("/api/members", cookies=_cookie("admin"))
    assert resp.status_code == 200
    members = resp.json()["members"]
    assert members[0]["role"] == "owner"


def test_viewer_cannot_list(client):
    resp = client.get("/api/members", cookies=_cookie("tg:100"))
    assert resp.status_code == 403


def test_admin_adds_then_deletes_member(client):
    add = client.post(
        "/api/members",
        json={"username": "bob", "role": "viewer"},
        cookies=_cookie("tg:200"),
    )
    assert add.status_code == 200
    assert add.json()["member"]["username"] == "bob"

    delete = client.delete("/api/members/u:bob", cookies=_cookie("tg:200"))
    assert delete.status_code == 200
    assert delete.json()["ok"] is True


def test_owner_is_protected_from_patch(client):
    resp = client.patch(
        "/api/members/42",
        json={"role": "admin"},
        cookies=_cookie("admin"),
    )
    assert resp.status_code == 400

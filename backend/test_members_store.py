import importlib

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    import backend.members_store as ms
    importlib.reload(ms)
    return ms


def test_owner_seeded_from_env(store):
    members = store.list_members()
    assert len(members) == 1
    assert members[0]["userId"] == "42"
    assert members[0]["role"] == "owner"


def test_allowlist_migrated_as_admins(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "100,200")
    import backend.members_store as ms
    importlib.reload(ms)
    roles = {m["userId"]: m["role"] for m in ms.list_members()}
    assert roles == {"42": "owner", "100": "admin", "200": "admin"}


def test_add_member_by_username_normalizes(store):
    m = store.add_member(username="@Alice", role="viewer", added_by="42")
    assert m["username"] == "alice"
    assert m["userId"] is None
    assert m["role"] == "viewer"


def test_resolve_pins_userid_on_first_match(store):
    store.add_member(username="alice", role="admin", added_by="42")
    resolved = store.resolve("777", "Alice")
    assert resolved["role"] == "admin"
    assert resolved["userId"] == "777"  # pinned + persisted
    # subsequent resolve by id alone works
    assert store.resolve("777", None)["role"] == "admin"


def test_resolve_unknown_returns_none(store):
    assert store.resolve("999", "nobody") is None


def test_add_duplicate_updates_role(store):
    store.add_member(user_id="100", role="viewer", added_by="42")
    store.add_member(user_id="100", role="admin", added_by="42")
    rows = [m for m in store.list_members() if m["userId"] == "100"]
    assert len(rows) == 1 and rows[0]["role"] == "admin"


def test_cannot_create_owner_via_add(store):
    with pytest.raises(ValueError):
        store.add_member(user_id="100", role="owner", added_by="42")


def test_owner_protected_from_role_change_and_removal(store):
    with pytest.raises(ValueError):
        store.set_role("42", "admin", actor="42")
    with pytest.raises(ValueError):
        store.remove_member("42", actor="42")


def test_set_role_and_remove(store):
    store.add_member(user_id="100", role="viewer", added_by="42")
    store.set_role("100", "admin", actor="42")
    assert store.resolve("100", None)["role"] == "admin"
    store.remove_member("100", actor="42")
    assert store.resolve("100", None) is None

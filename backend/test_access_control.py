import backend.access_control as ac


def test_capability_truth_table():
    assert ac.can("owner", "view") and ac.can("owner", "act") and ac.can("owner", "manage_team")
    assert ac.can("admin", "view") and ac.can("admin", "act") and ac.can("admin", "manage_team")
    assert ac.can("viewer", "view")
    assert not ac.can("viewer", "act")
    assert not ac.can("viewer", "manage_team")
    assert not ac.can(None, "view")
    assert not ac.can(None, "act")


def test_is_manager():
    assert ac.is_manager("owner") and ac.is_manager("admin")
    assert not ac.is_manager("viewer") and not ac.is_manager(None)


def test_role_for_uses_store(monkeypatch):
    monkeypatch.setattr(ac.members_store, "resolve", lambda uid, un: {"role": "admin"} if uid == "5" else None)
    assert ac.role_for("5", None) == "admin"
    assert ac.role_for("9", None) is None

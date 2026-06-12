# RBAC Roles (owner / admin / viewer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat env allowlist with a managed members system (owner/admin/viewer) that the owner and admins manage from both the Telegram bot and the web platform; viewers are read-only; unknown users are denied.

**Architecture:** One JSON members store (`members_store.py`) is the source of truth; a pure policy module (`access_control.py`) maps role→capability. Both surfaces resolve the caller's role **live** (Telegram: by user id; web: from the session subject) and gate every write through `can(role, "act")`. No session-cookie format change — role is resolved per request, so removals/role-changes take effect immediately.

**Tech Stack:** Python 3.11 / FastAPI, JSON file stores (mirrors `approval_store.py`), Vite + React 19 + TS frontend, pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-06-10-rbac-roles-design.md`

**Run tests with CI parity:** `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/members_store.py` (new) | Persisted members CRUD + owner seed + env migration + owner-protection. Single source of truth. |
| `backend/access_control.py` (new) | Pure role→capability policy. `can`, `is_manager`, `role_for`. No I/O except via `members_store`. |
| `backend/storage/members.json` (runtime) | Created on first load; not committed. |
| `backend/telegram_service.py` | `telegram_command_allowed` → role-aware; keep `allowed_telegram_values`. |
| `backend/routers/telegram.py` | Resolve role at top of `telegram_agent_command`; deny unknown; gate viewer writes; add `team:*` admin panel. |
| `backend/telegram_menus.py` | `BTN_TEAM`; `viewer_reply_keyboard()`; team-panel keyboards. |
| `backend/routers/members.py` (new) | `/api/members` CRUD, manager-gated. |
| `backend/webapp_auth.py` | `session_subject`, `session_role`; `user_allowed` → store-based. |
| `backend/routers/auth.py` | password login → owner; webapp-auth role; `/api/auth/session` returns role. |
| `backend/app.py` | session guard blocks non-GET `/api/*` for non-`act` roles; register members router. |
| `src/services/*`, `src/components/dashboard/*`, `src/App.tsx` | Team panel UI + viewer read-only + role from session. |

---

## Task 1: Members store

**Files:**
- Create: `backend/members_store.py`
- Test: `backend/test_members_store.py`

Record shape (the canonical type used everywhere): `{"userId": str|None, "username": str|None, "role": "owner"|"admin"|"viewer", "addedBy": str, "addedAt": str}`. Usernames are stored lowercased without a leading `@`. `member_key(m)` = `m["userId"]` if truthy else `"u:" + m["username"]`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_members_store.py
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_members_store.py -q`
Expected: FAIL (`No module named backend.members_store`).

- [ ] **Step 3: Implement `backend/members_store.py`**

```python
"""Managed team members + roles (owner/admin/viewer).

Single source of truth for who can use the agent and at what level. Mirrors the
JSON-file convention of approval_store / pending_context_store. The owner is
seeded from TELEGRAM_ADMIN_CHAT_ID and is immutable; on an empty store the legacy
TELEGRAM_ALLOWED_USER_IDS are imported as admins so access keeps working at deploy.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

_LOCK = threading.Lock()
ROLES = ("owner", "admin", "viewer")


def _path() -> str:
    return os.getenv("MEMBERS_STORE_PATH", "").strip() or os.path.join(
        os.path.dirname(__file__), "storage", "members.json"
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _norm_username(username: str | None) -> str | None:
    if not username:
        return None
    return username.strip().lstrip("@").lower() or None


def _read() -> list[dict[str, Any]]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(members: list[dict[str, Any]]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(members, fh, indent=2)
    os.replace(tmp, path)


def _seed_if_empty(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if members:
        return members
    seeded: list[dict[str, Any]] = []
    owner = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if owner:
        seeded.append({"userId": owner, "username": None, "role": "owner",
                       "addedBy": "system", "addedAt": _now()})
    for raw in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(","):
        uid = raw.strip()
        if uid and uid != owner:
            seeded.append({"userId": uid, "username": None, "role": "admin",
                           "addedBy": "system", "addedAt": _now()})
    if seeded:
        _write(seeded)
    return seeded


def member_key(member: dict[str, Any]) -> str:
    return str(member["userId"]) if member.get("userId") else "u:" + str(member.get("username"))


def list_members() -> list[dict[str, Any]]:
    with _LOCK:
        return _seed_if_empty(_read())


def _find(members: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for m in members:
        if member_key(m) == key:
            return m
    return None


def resolve(user_id: str | None, username: str | None) -> dict[str, Any] | None:
    """Return the member matching this Telegram user, pinning the numeric id on a
    first-time username match. None means 'no access'."""
    uid = str(user_id).strip() if user_id else None
    uname = _norm_username(username)
    with _LOCK:
        members = _seed_if_empty(_read())
        if uid:
            hit = next((m for m in members if str(m.get("userId")) == uid), None)
            if hit:
                return dict(hit)
        if uname:
            hit = next((m for m in members if m.get("username") == uname), None)
            if hit:
                if uid and not hit.get("userId"):
                    hit["userId"] = uid  # pin + persist
                    _write(members)
                return dict(hit)
    return None


def add_member(*, user_id: str | None = None, username: str | None = None,
               role: str, added_by: str) -> dict[str, Any]:
    if role not in ("admin", "viewer"):
        raise ValueError("role must be 'admin' or 'viewer'")
    uid = str(user_id).strip() if user_id else None
    uname = _norm_username(username)
    if not uid and not uname:
        raise ValueError("a username or numeric id is required")
    with _LOCK:
        members = _seed_if_empty(_read())
        existing = None
        if uid:
            existing = next((m for m in members if str(m.get("userId")) == uid), None)
        if not existing and uname:
            existing = next((m for m in members if m.get("username") == uname), None)
        if existing:
            if existing["role"] == "owner":
                raise ValueError("the owner can't be changed")
            existing["role"] = role
            if uid:
                existing["userId"] = uid
            if uname:
                existing["username"] = uname
            _write(members)
            return dict(existing)
        record = {"userId": uid, "username": uname, "role": role,
                  "addedBy": added_by, "addedAt": _now()}
        members.append(record)
        _write(members)
        return dict(record)


def set_role(key: str, role: str, *, actor: str) -> dict[str, Any]:
    if role not in ("admin", "viewer"):
        raise ValueError("role must be 'admin' or 'viewer'")
    with _LOCK:
        members = _seed_if_empty(_read())
        target = _find(members, key)
        if not target:
            raise KeyError(key)
        if target["role"] == "owner":
            raise ValueError("the owner can't be changed")
        target["role"] = role
        _write(members)
        return dict(target)


def remove_member(key: str, *, actor: str) -> None:
    with _LOCK:
        members = _seed_if_empty(_read())
        target = _find(members, key)
        if not target:
            raise KeyError(key)
        if target["role"] == "owner":
            raise ValueError("the owner can't be removed")
        members = [m for m in members if member_key(m) != key]
        _write(members)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_members_store.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/members_store.py backend/test_members_store.py
git commit -m "feat(rbac): managed members store with owner seed + protection"
```

---

## Task 2: Access-control policy

**Files:**
- Create: `backend/access_control.py`
- Test: `backend/test_access_control.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_access_control.py
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_access_control.py -q`
Expected: FAIL (`No module named backend.access_control`).

- [ ] **Step 3: Implement `backend/access_control.py`**

```python
"""Pure role -> capability policy. The only authority on what a role may do."""

from __future__ import annotations

from . import members_store

CAPABILITIES: dict[str, set[str]] = {
    "owner": {"view", "act", "manage_team"},
    "admin": {"view", "act", "manage_team"},
    "viewer": {"view"},
}


def can(role: str | None, capability: str) -> bool:
    return bool(role) and capability in CAPABILITIES.get(role, set())


def is_manager(role: str | None) -> bool:
    return role in ("owner", "admin")


def role_for(user_id: str | None, username: str | None) -> str | None:
    member = members_store.resolve(user_id, username)
    return member["role"] if member else None
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_access_control.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/access_control.py backend/test_access_control.py
git commit -m "feat(rbac): pure role->capability policy module"
```

---

## Task 3: Telegram role gate (deny unknown, block viewer writes)

**Files:**
- Modify: `backend/telegram_service.py` (`telegram_command_allowed`, ~line 117)
- Modify: `backend/routers/telegram.py` (`telegram_agent_command`, ~line 531)
- Modify: `backend/telegram_menus.py` (viewer keyboard)
- Test: `backend/test_telegram_roles.py` (new)

**Design:** At the top of `telegram_agent_command` (after the secret check and `normalize_telegram_command`), resolve the role once:
```python
role = access_control.role_for(command.get("userId") or command.get("chatId"), command.get("username"))
```
- `role is None` → send the no-access message and return.
- For a **viewer**, only read paths are allowed. Define the set of write actions and block them.

The write callback actions to block for viewers: `{"approve", "dryrun", "applylive", "cancel", "reject", "changes", "needs_changes", "agap", "manage", "view"}` plus free-text agentic and the `team:*` panel. Read actions allowed for viewers: `menu`, `cmp`, `apv`, and reply-button reads (`kpis/suggestions/status/alerts/campaigns/pending`). `team:*` requires `is_manager`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_telegram_roles.py
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "s3cret")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    import backend.members_store as ms
    importlib.reload(ms)
    import backend.app as app_module
    importlib.reload(app_module)
    sent = []
    import backend.telegram_outbound as outbound
    monkeypatch.setattr(outbound, "send_telegram_message_sync",
                        lambda text, **kw: sent.append((text, kw)) or {"ok": True})
    return TestClient(app_module.app), sent, ms


def _post(client, **payload):
    payload.setdefault("secret", "s3cret")
    return client.post("/api/telegram/command", json=payload)


def test_unknown_user_denied(client):
    c, sent, ms = client
    r = _post(c, chat_id=999, user_id=999, text="hello")
    assert r.status_code == 200
    assert any("access" in t.lower() for t, _ in sent)


def test_viewer_freetext_blocked(client):
    c, sent, ms = client
    ms.add_member(user_id="100", role="viewer", added_by="42")
    r = _post(c, chat_id=100, user_id=100, text="pause my best campaign")
    assert r.status_code == 200
    assert any("viewer" in t.lower() for t, _ in sent)


def test_viewer_write_callback_blocked(client):
    c, sent, ms = client
    ms.add_member(user_id="100", role="viewer", added_by="42")
    r = _post(c, callback_query={"id": "1", "data": "approve:abc",
                                 "from": {"id": 100}, "message": {"chat": {"id": 100}}})
    body = r.json()
    assert body.get("ok") is False or any("viewer" in t.lower() for t, _ in sent)


def test_owner_freetext_reaches_agentic(client, monkeypatch):
    c, sent, ms = client
    import backend.agentic_chat as agentic
    monkeypatch.setattr(agentic, "agentic_reply", _fake_reply)
    r = _post(c, chat_id=42, user_id=42, text="what is active?")
    assert r.json().get("agentic") is True


async def _fake_reply(message, *, operator_key):
    return "ok"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_telegram_roles.py -q`
Expected: FAIL (no-access message not sent / viewer not blocked).

- [ ] **Step 3: Implement the gate**

In `backend/routers/telegram.py`, add imports `from .. import access_control` and a constant + helper near the top of the module:

```python
_VIEWER_BLOCKED_ACTIONS = {
    "approve", "dryrun", "applylive", "cancel", "reject", "changes",
    "needs_changes", "agap", "manage", "view",
}
_NO_ACCESS = "🚫 You don't have access to this bot. You can leave."
_VIEWER_NOTICE = ("👀 You have <b>viewer</b> access — browse with the buttons below. "
                  "I can't take requests or make changes for you.")
```

Replace the allow check at `telegram_agent_command` (currently `if not telegram_command_allowed(command): raise HTTPException(403...)`) with:

```python
    role = access_control.role_for(
        command.get("userId") or command.get("chatId"), command.get("username")
    )
    if role is None:
        _send(command, _NO_ACCESS)
        return {"ok": False, "telegram": command, "denied": "no_access"}

    action = command.get("action")
    if not access_control.is_manager(role) and action in _VIEWER_BLOCKED_ACTIONS:
        _send(command, _VIEWER_NOTICE, parse_mode="HTML", reply_markup=viewer_reply_keyboard())
        return {"ok": False, "telegram": command, "denied": "viewer"}
    if not access_control.is_manager(role) and (action and action.startswith("team")):
        _send(command, _VIEWER_NOTICE, parse_mode="HTML")
        return {"ok": False, "telegram": command, "denied": "viewer_team"}
```

Then, just before the free-text agentic block (the line `from .. import agentic_chat`), insert the viewer free-text guard:

```python
    if not access_control.is_manager(role):
        # Viewer typed free text: one short notice, never the agentic brain.
        if not REPLY_BUTTON_ACTIONS.get(text.strip().lower()) and lowered not in {"start", "menu", "kpis", "suggestions", "status", "alerts"}:
            _send(command, _VIEWER_NOTICE, parse_mode="HTML", reply_markup=viewer_reply_keyboard())
            return {"ok": False, "telegram": command, "denied": "viewer_chat"}
```

In `backend/telegram_menus.py`, add `BTN_TEAM = "👥 Team"`, register it in `REPLY_BUTTON_ACTIONS` mapping to `"team"`, add it to `main_reply_keyboard()` rows (managers' keyboard), and add a viewer keyboard:

```python
BTN_TEAM = "👥 Team"
# ... REPLY_BUTTON_ACTIONS[BTN_TEAM.lower()] = "team"

def viewer_reply_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": BTN_KPIS}, {"text": BTN_STATUS}],
            [{"text": BTN_ALERTS}, {"text": BTN_CAMPAIGNS}],
            [{"text": BTN_PENDING}],
        ],
        "resize_keyboard": True,
    }
```

Add `BTN_TEAM` to the manager `main_reply_keyboard()` rows (e.g. append `[{"text": BTN_ASK}, {"text": BTN_TEAM}]`). Import `viewer_reply_keyboard` and `REPLY_BUTTON_ACTIONS` where used in `telegram.py`.

`backend/telegram_service.py`: keep `telegram_command_allowed` for back-compat but it is no longer the gate (the router now uses `access_control`). Leave `allowed_telegram_values` as-is (used by the migration).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_telegram_roles.py backend/test_telegram_command_api.py -q`
Expected: PASS (new role tests + existing command-api tests still green; the existing tests seed owner `42` so they remain authorized).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/telegram.py backend/telegram_menus.py backend/telegram_service.py backend/test_telegram_roles.py
git commit -m "feat(rbac): telegram role gate — deny unknown, viewers read-only"
```

---

## Task 4: Telegram team admin panel (list / add / role / remove)

**Files:**
- Modify: `backend/routers/telegram.py` (add `_handle_team`, wire `action == "team"` reply button + `team:*` callbacks)
- Modify: `backend/telegram_menus.py` (team keyboards)
- Modify: `backend/pending_context_store.py` (reuse for the add-capture step — no change if it already stores arbitrary dicts)
- Test: `backend/test_telegram_team.py` (new)

**Callbacks:** `team:list`, `team:add`, `team:role:<key>`, `team:setrole:<key>~<role>`, `team:remove:<key>`. The `~` separates key and role to survive the first-colon split in `normalize_telegram_command` (which keeps everything after the first colon as `approvalId`). So `command["approvalId"]` carries e.g. `setrole:100~admin`; parse it inside `_handle_team`.

**Add flow:** `team:add` stores `set_pending(operator_key, {"kind": "team_add"})` and asks the manager to send `@username admin` or `123456 viewer`. The free-text handler, before the agentic block, checks for a pending `team_add` and parses `"<id-or-@username> <role>"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_telegram_team.py
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("PENDING_CONTEXT_STORE_PATH", str(tmp_path / "pending.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_COMMAND_SECRET", "s3cret")
    import backend.members_store as ms
    importlib.reload(ms)
    import backend.app as app_module
    importlib.reload(app_module)
    sent = []
    import backend.telegram_outbound as outbound
    monkeypatch.setattr(outbound, "send_telegram_message_sync",
                        lambda text, **kw: sent.append((text, kw)) or {"ok": True})
    monkeypatch.setattr(outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    return TestClient(app_module.app), sent, ms


def _post(c, **payload):
    payload.setdefault("secret", "s3cret")
    return c.post("/api/telegram/command", json=payload)


def test_owner_can_add_member_via_capture(ctx):
    c, sent, ms = ctx
    _post(c, chat_id=42, user_id=42, callback_query={"id": "1", "data": "team:add",
          "from": {"id": 42}, "message": {"chat": {"id": 42}}})
    _post(c, chat_id=42, user_id=42, text="@alice admin")
    roles = {m.get("username"): m["role"] for m in ms.list_members() if m.get("username")}
    assert roles.get("alice") == "admin"


def test_owner_can_remove_member(ctx):
    c, sent, ms = ctx
    ms.add_member(user_id="100", role="viewer", added_by="42")
    _post(c, chat_id=42, user_id=42, callback_query={"id": "2", "data": "team:remove:100",
          "from": {"id": 42}, "message": {"chat": {"id": 42}}})
    assert ms.resolve("100", None) is None


def test_owner_row_cannot_be_removed(ctx):
    c, sent, ms = ctx
    r = _post(c, chat_id=42, user_id=42, callback_query={"id": "3", "data": "team:remove:42",
              "from": {"id": 42}, "message": {"chat": {"id": 42}}})
    assert ms.resolve("42", None)["role"] == "owner"
    assert any("owner" in t.lower() for t, _ in sent)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_telegram_team.py -q`
Expected: FAIL (`team:*` not handled).

- [ ] **Step 3: Implement `_handle_team` and wiring**

In `backend/routers/telegram.py`, dispatch the reply button and callbacks. Add after the existing `if action == "apv":` block:

```python
    if action == "team":
        return _open_team_panel(command)
    if action and action.startswith("team"):
        return _handle_team(command, callback)
```

Wait — the reply-button label "👥 Team" maps via `REPLY_BUTTON_ACTIONS` to `"team"` and is handled in `_handle_menu`. Route it: in `_handle_menu`, add `if target == "team": return _open_team_panel(command)`. For callbacks, the action is `"team"` (first-colon split) so `_handle_team` parses `command["approvalId"]` (the tail).

Add the handlers:

```python
def _open_team_panel(command: dict[str, Any]) -> dict[str, Any]:
    from .. import members_store
    members = members_store.list_members()
    _send(command, _team_text(members), parse_mode="HTML",
          reply_markup=team_panel_keyboard(members))
    return {"ok": True, "telegram": command, "team": "list"}


def _handle_team(command: dict[str, Any], callback: dict[str, Any]) -> dict[str, Any]:
    from .. import members_store
    from ..pending_context_store import operator_key, set_pending
    tail = command.get("approvalId") or ""  # e.g. "add" | "remove:100" | "setrole:100~admin"
    verb, _, rest = tail.partition(":")
    actor = str(command.get("userId") or command.get("chatId"))
    if verb == "add":
        set_pending(operator_key(telegram_chat_id=command.get("chatId")), {"kind": "team_add"})
        _send(command, "Send the new member as <code>@username admin</code> or "
                       "<code>123456 viewer</code>.", parse_mode="HTML")
        return {"ok": True, "telegram": command, "team": "add_prompt"}
    if verb == "remove":
        try:
            members_store.remove_member(rest, actor=actor)
            _send(command, "✅ Removed.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        except KeyError:
            _send(command, "That member is no longer on the team.")
        return _open_team_panel(command)
    if verb == "setrole":
        key, _, role = rest.partition("~")
        try:
            members_store.set_role(key, role, actor=actor)
            _send(command, f"✅ Role set to {role}.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        return _open_team_panel(command)
    return _open_team_panel(command)
```

Add the `team_add` capture in the free-text path (BEFORE the agentic block, managers only):

```python
    from ..pending_context_store import get_pending as _get_pending
    _pend = _get_pending(operator_key(telegram_chat_id=command.get("chatId")))
    if _pend and _pend.get("kind") == "team_add" and access_control.is_manager(role):
        from ..pending_context_store import clear_pending
        from .. import members_store
        parts = text.split()
        ident, new_role = (parts[0], parts[1].lower()) if len(parts) >= 2 else (text.strip(), "viewer")
        kwargs = {"user_id": ident} if ident.isdigit() else {"username": ident}
        try:
            members_store.add_member(role=new_role, added_by=str(command.get("userId")), **kwargs)
            clear_pending(operator_key(telegram_chat_id=command.get("chatId")))
            _send(command, f"✅ Added {ident} as {new_role}.")
        except ValueError as e:
            _send(command, f"⚠️ {e}")
        return {"ok": True, "telegram": command, "team": "added"}
```

In `backend/telegram_menus.py` add the keyboards:

```python
def team_panel_keyboard(members: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [[{"text": "➕ Add member", "callback_data": "team:add"}]]
    for m in members:
        key = str(m["userId"]) if m.get("userId") else "u:" + str(m.get("username"))
        label = (m.get("username") and "@" + m["username"]) or m.get("userId") or "?"
        if m["role"] == "owner":
            rows.append([{"text": f"👑 {label} (owner)", "callback_data": "team:list"}])
        else:
            rows.append([
                {"text": f"{label} · {m['role']}", "callback_data": f"team:setrole:{key}~{'viewer' if m['role']=='admin' else 'admin'}"},
                {"text": "🗑", "callback_data": f"team:remove:{key}"},
            ])
    return {"inline_keyboard": rows}
```

And a `_team_text(members)` helper in `telegram.py` rendering a short HTML list. Verify every `callback_data` stays ≤ 64 bytes (numeric ids + short role keep it well under).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_telegram_team.py backend/test_telegram_menu.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/telegram.py backend/telegram_menus.py backend/test_telegram_team.py
git commit -m "feat(rbac): telegram team admin panel (add/role/remove)"
```

---

## Task 5: Web members API

**Files:**
- Create: `backend/routers/members.py`
- Modify: `backend/app.py` (register router; add to import list near line 188)
- Modify: `backend/webapp_auth.py` (add `session_subject`, `session_role`)
- Test: `backend/test_members_api.py` (new)

**Role from session:** `session_subject(token)` parses the sub (`"admin"` or `"tg:<id>"`). `session_role(token)` → `"owner"` for `"admin"`; for `"tg:<id>"`, `access_control.role_for(id, None)`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_members_api.py
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("DASHBOARD_SESSION_AUTH", "true")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    import backend.members_store as ms
    importlib.reload(ms)
    import backend.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app), ms


def _session(sub):
    from backend.webapp_auth import make_session
    return make_session(sub)


def test_owner_lists_members(client):
    c, ms = client
    c.cookies.set("session", _session("admin"))
    r = c.get("/api/members")
    assert r.status_code == 200
    assert r.json()["members"][0]["role"] == "owner"


def test_viewer_forbidden(client):
    c, ms = client
    ms.add_member(user_id="100", role="viewer", added_by="42")
    c.cookies.set("session", _session("tg:100"))
    assert c.get("/api/members").status_code == 403


def test_admin_can_add_and_remove(client):
    c, ms = client
    ms.add_member(user_id="200", role="admin", added_by="42")
    c.cookies.set("session", _session("tg:200"))
    r = c.post("/api/members", json={"username": "@bob", "role": "viewer"})
    assert r.status_code == 200
    assert ms.resolve(None, "bob")["role"] == "viewer"
    assert c.request("DELETE", "/api/members/u:bob").status_code == 200


def test_owner_protected_via_api(client):
    c, ms = client
    c.cookies.set("session", _session("admin"))
    assert c.patch("/api/members/42", json={"role": "admin"}).status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_members_api.py -q`
Expected: FAIL (404 — router not registered).

- [ ] **Step 3: Implement**

`backend/webapp_auth.py` — add:

```python
def session_subject(token: str | None) -> str | None:
    if not valid_session(token):
        return None
    sub, _exp, _sig = token.rsplit(".", 2)
    return sub


def session_role(token: str | None) -> str | None:
    sub = session_subject(token)
    if sub is None:
        return None
    if sub == "admin":
        return "owner"
    if sub.startswith("tg:"):
        from .access_control import role_for
        return role_for(sub[3:], None)
    return None
```

`backend/routers/members.py`:

```python
"""Team members CRUD for the web platform (manager-gated)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import access_control, members_store
from ..webapp_auth import COOKIE_NAME, dashboard_auth_enabled, session_role

router = APIRouter()


def _require_manager(request: Request) -> str:
    if not dashboard_auth_enabled():
        return "owner"  # dev/test open mode
    role = session_role(request.cookies.get(COOKIE_NAME))
    if not access_control.is_manager(role):
        raise HTTPException(status_code=403, detail="Manager access required.")
    return role


class AddMemberRequest(BaseModel):
    username: str | None = None
    userId: str | None = None
    role: str


class SetRoleRequest(BaseModel):
    role: str


@router.get("/api/members")
def list_members(request: Request) -> dict:
    _require_manager(request)
    return {"members": members_store.list_members()}


@router.post("/api/members")
def add_member(body: AddMemberRequest, request: Request) -> dict:
    actor = _require_manager(request)
    try:
        member = members_store.add_member(
            user_id=body.userId, username=body.username, role=body.role, added_by=actor
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "member": member}


@router.patch("/api/members/{key:path}")
def set_role(key: str, body: SetRoleRequest, request: Request) -> dict:
    actor = _require_manager(request)
    try:
        member = members_store.set_role(key, body.role, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Member not found.") from e
    return {"ok": True, "member": member}


@router.delete("/api/members/{key:path}")
def remove_member(key: str, request: Request) -> dict:
    actor = _require_manager(request)
    try:
        members_store.remove_member(key, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Member not found.") from e
    return {"ok": True}
```

`backend/app.py` — import `from .routers import members as members_router` (with the other router imports) and add `members_router` to the `for module in (...)` registration tuple.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_members_api.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/members.py backend/webapp_auth.py backend/app.py backend/test_members_api.py
git commit -m "feat(rbac): web members API + session role resolution"
```

---

## Task 6: Web auth role wiring + viewer read-only guard

**Files:**
- Modify: `backend/routers/auth.py` (`user_allowed` via store; `/api/auth/session` returns role)
- Modify: `backend/webapp_auth.py` (`user_allowed` → store-based)
- Modify: `backend/app.py` (`_session_guard`: block non-GET for non-`act` roles)
- Test: `backend/test_webapp_auth.py` (extend), `backend/test_session_role_guard.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_session_role_guard.py
import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("DASHBOARD_SESSION_AUTH", "true")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    import backend.members_store as ms
    importlib.reload(ms)
    import backend.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app), ms


def _session(sub):
    from backend.webapp_auth import make_session
    return make_session(sub)


def test_session_endpoint_returns_role(client):
    c, ms = client
    c.cookies.set("session", _session("admin"))
    assert c.get("/api/auth/session").json()["role"] == "owner"


def test_viewer_blocked_from_mutations(client):
    c, ms = client
    ms.add_member(user_id="100", role="viewer", added_by="42")
    c.cookies.set("session", _session("tg:100"))
    # any non-GET /api mutation must be 403 for a viewer
    r = c.post("/api/meta/sync", json={})
    assert r.status_code == 403


def test_admin_allowed_through_guard(client):
    c, ms = client
    ms.add_member(user_id="200", role="admin", added_by="42")
    c.cookies.set("session", _session("tg:200"))
    # admin passes the guard (endpoint may 404/422 but NOT 403)
    assert c.post("/api/meta/sync", json={}).status_code != 403
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/test_session_role_guard.py -q`
Expected: FAIL (no `role` field; viewer not blocked).

- [ ] **Step 3: Implement**

`backend/webapp_auth.py` — replace `user_allowed` body to consult the store:

```python
def user_allowed(user: dict[str, Any]) -> bool:
    """Mini App users must be a known team member."""
    from .access_control import role_for
    return role_for(str(user.get("id")), user.get("username")) is not None
```

`backend/routers/auth.py` — `/api/auth/session` returns role:

```python
@router.get("/api/auth/session")
def session_status(request: Request) -> dict[str, Any]:
    from ..webapp_auth import session_role
    token = request.cookies.get(COOKIE_NAME)
    if not dashboard_auth_enabled():
        return {"authenticated": True, "role": "owner"}
    authed = valid_session(token)
    return {"authenticated": bool(authed), "role": session_role(token) if authed else None}
```

`backend/app.py` `_session_guard` — after the `valid_session` check passes, block mutations for non-`act` roles:

```python
    if dashboard_auth_enabled():
        path = request.url.path
        if path.startswith("/api/") and path not in _AUTH_PUBLIC_PATHS:
            token = request.cookies.get(COOKIE_NAME)
            if not valid_session(token):
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                from .access_control import can
                from .webapp_auth import session_role
                if not can(session_role(token), "act"):
                    return JSONResponse({"detail": "Read-only access."}, status_code=403)
    return await call_next(request)
```

(Add `/api/members` is already manager-gated in its router; the guard's blanket mutation block is fine because managers have `act`.)

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_session_role_guard.py backend/test_webapp_auth.py -q`
Expected: PASS. Fix any `test_webapp_auth.py` cases that assumed the old env-allowlist `user_allowed` by seeding the member via `members_store.add_member` / `TELEGRAM_ADMIN_CHAT_ID`.

- [ ] **Step 5: Commit**

```bash
git add backend/webapp_auth.py backend/routers/auth.py backend/app.py backend/test_session_role_guard.py backend/test_webapp_auth.py
git commit -m "feat(rbac): web viewer read-only guard + role in session endpoint"
```

---

## Task 7: Frontend — Team panel + viewer read-only

**Files:**
- Create: `src/components/dashboard/TeamPanel.tsx`
- Create: `src/services/members.ts`
- Modify: `src/App.tsx` (read `role` from `/api/auth/session`, pass down; gate UI)
- Modify: `src/components/Dashboard.tsx` (render TeamPanel for managers; hide write controls for viewers)
- Test: `src/components/dashboard/TeamPanel.test.tsx`, extend `src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/dashboard/TeamPanel.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { TeamPanel } from './TeamPanel'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/members' && (!init || init.method === undefined))
      return new Response(JSON.stringify({ members: [
        { userId: '42', username: null, role: 'owner' },
        { userId: '100', username: 'alice', role: 'viewer' },
      ] }), { status: 200 })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }))
})

describe('TeamPanel', () => {
  it('lists members and shows owner as locked', async () => {
    render(<TeamPanel />)
    await waitFor(() => expect(screen.getByText(/owner/i)).toBeInTheDocument())
    expect(screen.getByText(/alice/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- TeamPanel`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`src/services/members.ts`:

```ts
export type Member = { userId: string | null; username: string | null; role: 'owner' | 'admin' | 'viewer' }

export async function listMembers(): Promise<Member[]> {
  const r = await fetch('/api/members')
  if (!r.ok) throw new Error('forbidden')
  return (await r.json()).members
}
export async function addMember(input: { username?: string; userId?: string; role: 'admin' | 'viewer' }) {
  const r = await fetch('/api/members', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
  if (!r.ok) throw new Error((await r.json()).detail || 'failed')
}
export async function setRole(key: string, role: 'admin' | 'viewer') {
  await fetch(`/api/members/${encodeURIComponent(key)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) })
}
export async function removeMember(key: string) {
  await fetch(`/api/members/${encodeURIComponent(key)}`, { method: 'DELETE' })
}
export function memberKey(m: Member): string {
  return m.userId ?? 'u:' + m.username
}
```

`src/components/dashboard/TeamPanel.tsx` — a panel that lists members, an add form (username/ID + role select), role toggle, and remove; the owner row is rendered read-only. Use the `members.ts` service. (Keep it a focused component; match existing dashboard component styling.)

`src/App.tsx` — extend the session bootstrap to capture role:

```ts
const response = await fetch('/api/auth/session')
const json = (await response.json()) as { authenticated?: boolean; role?: string | null }
// store json.role in state; pass to Dashboard
```

`src/components/Dashboard.tsx` — accept a `role` prop; render `<TeamPanel/>` only when `role === 'owner' || role === 'admin'`; when `role === 'viewer'`, hide approval buttons + the chat composer and show a "Viewer · read-only" badge.

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- TeamPanel` then `npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/dashboard/TeamPanel.tsx src/services/members.ts src/App.tsx src/components/Dashboard.tsx src/components/dashboard/TeamPanel.test.tsx
git commit -m "feat(rbac): web team panel + viewer read-only UI"
```

---

## Task 8: Integration — full suite, frontend build

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: PASS (494 prior + new RBAC tests; fix any test that relied on the old open allowlist by seeding a member).

- [ ] **Step 2: Frontend**

Run: `npm test && npm run lint && npm run build`
Expected: all PASS; `dist/` built.

- [ ] **Step 3: Commit any test fixups**

```bash
git add -A && git commit -m "test(rbac): integrate roles across suite"
```

---

## Parallelization & merge strategy

- **WS-1 = Tasks 1 + 2** (foundation: `members_store.py`, `access_control.py`). No overlap. **Must land first** — everything imports it. Build on the branch directly (small), then fan out.
- **WS-2 = Tasks 3 + 4** (Telegram: `routers/telegram.py`, `telegram_menus.py`, `telegram_service.py`). Worktree-isolated.
- **WS-3 = Tasks 5 + 6** (Web backend: `routers/members.py`, `webapp_auth.py`, `routers/auth.py`, `app.py`). Worktree-isolated. **Note:** both WS-2 and WS-3 touch nothing in common except `app.py` (WS-3 only) — disjoint.
- **WS-4 = Task 7** (frontend) — depends on WS-3's API shape; run after WS-3 merges (or in parallel against the documented API in `members.ts`).

Merge order: WS-1 → WS-3 → WS-2 → WS-4 → Task 8 integration. `app.py` is edited only by WS-3, so no dispatch-chain conflicts.

---

## Verification (live, after merge + deploy authorization)

1. Telegram as owner: tap **👥 Team** → add a coworker by `@username viewer` → they `/start`: they get the viewer keyboard, can browse KPIs/Status/Campaigns, but free text returns the viewer notice and approve buttons do nothing.
2. Promote them to admin from the panel → they can now chat + approve.
3. A non-added user `/start`s → "You don't have access to this bot. You can leave."
4. Web: owner opens **Settings → Team**, adds/removes/realms a member; a viewer session sees read-only dashboard (no approve buttons, no chat box) and any mutation returns 403.
5. Owner row can never be demoted/removed on either surface.
6. Deploy: build frontend → tar `backend/` (+`dist/`) → scp → `systemctl restart meta-ad-agent` → health ok. (Confirm before the production deploy.)
```

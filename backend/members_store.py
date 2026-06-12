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

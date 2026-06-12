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

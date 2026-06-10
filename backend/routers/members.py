"""Team members CRUD for the web platform (manager-gated)."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from .. import access_control, members_store
from ..webapp_auth import COOKIE_NAME, dashboard_auth_enabled, session_role
router = APIRouter()
def _require_manager(request: Request) -> str:
    if not dashboard_auth_enabled():
        return "owner"
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
        member = members_store.add_member(user_id=body.userId, username=body.username, role=body.role, added_by=actor)
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

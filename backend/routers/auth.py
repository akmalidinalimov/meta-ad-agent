"""Session auth endpoints for the dashboard (browser login) + Telegram Mini App."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..webapp_auth import (
    COOKIE_NAME,
    dashboard_auth_enabled,
    make_session,
    user_allowed,
    valid_session,
    validate_init_data,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TTL = 7 * 24 * 3600


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_TTL,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


class LoginRequest(BaseModel):
    password: str


@router.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    expected = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not expected or body.password != expected:
        raise HTTPException(status_code=401, detail="Invalid password.")
    _set_session_cookie(response, make_session("admin"))
    return {"ok": True}


class WebAppAuthRequest(BaseModel):
    initData: str


@router.post("/api/telegram/webapp-auth")
def webapp_auth(body: WebAppAuthRequest, response: Response) -> dict[str, Any]:
    user = validate_init_data(body.initData)
    if not user:
        # validate_init_data already logged the precise cause (missing bot token /
        # missing hash / bad hash / stale auth_date / malformed user).
        logger.warning("webapp-auth rejected: invalid initData user=unknown")
        raise HTTPException(status_code=401, detail="Telegram authentication failed.")
    if not user_allowed(user):
        logger.warning("webapp-auth rejected: user not in allowlist user=%s", user.get("id"))
        raise HTTPException(status_code=401, detail="Telegram authentication failed.")
    _set_session_cookie(response, make_session(f"tg:{user.get('id')}"))
    return {"ok": True, "user": {"id": user.get("id"), "username": user.get("username")}}


@router.get("/api/auth/session")
def session_status(request: Request) -> dict[str, Any]:
    # When the guard is off, the app is open, so report authenticated so the SPA
    # skips the login screen.
    authenticated = not dashboard_auth_enabled() or valid_session(request.cookies.get(COOKIE_NAME))
    return {"authenticated": bool(authenticated)}


@router.post("/api/auth/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

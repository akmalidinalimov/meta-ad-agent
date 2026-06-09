"""App-level session auth for the dashboard + Telegram Mini App.

One signed session cookie gates the dashboard data API. Two ways to mint it:
- Browser: POST /api/auth/login with the admin password.
- Telegram Mini App: POST /api/telegram/webapp-auth with the signed initData,
  which we validate via HMAC with the bot token (Telegram's documented scheme)
  and check against the operator allowlist.

The session guard is OFF unless DASHBOARD_SESSION_AUTH=true, so tests/dev are
unaffected; production turns it on at the same time Caddy's basic-auth is removed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import parse_qsl

COOKIE_NAME = "session"
_DEFAULT_TTL = 7 * 24 * 3600


def dashboard_auth_enabled() -> bool:
    return os.getenv("DASHBOARD_SESSION_AUTH", "").strip().lower() == "true"


def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _session_secret() -> bytes:
    secret = os.getenv("SESSION_SECRET", "").strip()
    if secret:
        return secret.encode()
    # Always have a secret: derive one from the bot token so sessions can't be
    # forged even if SESSION_SECRET is unset.
    return hashlib.sha256(("session-v1:" + _bot_token()).encode()).digest()


def validate_init_data(init_data: str, *, max_age_seconds: int = 86400) -> dict[str, Any] | None:
    """Validate Telegram WebApp initData; return the parsed user dict or None.

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token); the data hash is
    HMAC_SHA256(key=secret_key, msg=data_check_string) over the sorted k=v lines.
    """
    token = _bot_token()
    if not init_data or not token:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    # Newer Telegram clients add an Ed25519 `signature` field that is NOT part of the
    # HMAC data-check-string; including it makes the hash mismatch. Drop it.
    pairs.pop("signature", None)
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age_seconds and (time.time() - auth_date) > max_age_seconds:
        return None
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    return user or None


def user_allowed(user: dict[str, Any]) -> bool:
    """Mini App users must be on the same allowlist the bot uses (no list = allow)."""
    from .telegram_service import allowed_telegram_values

    allowed = allowed_telegram_values("TELEGRAM_ALLOWED_USER_IDS")
    admin = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    if admin:
        allowed.add(admin)
    if not allowed:
        return True
    return str(user.get("id")) in allowed


def make_session(sub: str, *, ttl_seconds: int = _DEFAULT_TTL) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{sub}.{exp}"
    signature = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        sub, exp, signature = token.rsplit(".", 2)
    except ValueError:
        return False
    payload = f"{sub}.{exp}"
    expected = hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False

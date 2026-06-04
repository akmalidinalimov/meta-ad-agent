"""Lightweight API-key auth for state-changing routes.

Hosted/multi-user safety: when AGENT_API_KEY is set, every state-changing request
must present a matching X-API-Key header. When it is unset (local single-operator
use and the test suite), auth is disabled so nothing breaks. This protects the
money-moving approval/execute endpoints from unauthorized callers without forcing a
key on read-only dashboard loads.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.getenv("AGENT_API_KEY", "").strip()
    if not expected:
        return  # auth disabled
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")

"""Central configuration helpers.

Single source of truth for feature flags and origins that were previously parsed
inline (and slightly differently) in multiple routers. Import these instead of
re-reading os.environ so the semantics can't drift.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def live_writes_enabled() -> bool:
    """Whether live Meta writes are permitted (the env kill-switch)."""
    return os.getenv("META_LIVE_WRITES_ENABLED", "").strip().lower() == "true"


def allowed_origins() -> list[str]:
    raw = os.getenv("FUNNEL_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

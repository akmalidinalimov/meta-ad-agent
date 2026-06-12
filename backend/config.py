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


def reasoning_provider() -> str:
    """Which LLM backend the reasoning seam routes to.

    "openai" (default) keeps the original behavior; "anthropic"/"claude" routes
    to the Anthropic Messages API. Anything else falls back to openai.
    """
    return os.getenv("REASONING_PROVIDER", "openai").strip().lower() or "openai"


def openai_model() -> str:
    """OpenAI chat-completions model id (with the long-standing default)."""
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"


def anthropic_model() -> str:
    """Anthropic Messages API model id."""
    return os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"

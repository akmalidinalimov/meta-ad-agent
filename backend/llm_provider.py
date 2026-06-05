"""Pluggable reasoning provider seam.

A single ``reason()`` entry point hides which LLM backend actually answers, so
the agent layer can stay provider-agnostic. Today two backends are wired:

* ``openai``  — the original chat-completions httpx call (unchanged semantics).
* ``anthropic`` (aka ``claude``) — the Anthropic Messages API via the official
  SDK, with prompt caching enabled on the (large, reused) system block.

The degradation contract is identical for both backends and matches the rest of
the codebase so callers never have to special-case a provider:

* return ``None`` when the selected provider's API key is missing — the caller
  then uses its deterministic template.
* return a string starting with ``"LLM reasoning unavailable (<provider>): "``
  on any error — callers detect this with ``.startswith`` and degrade.
* otherwise return the model's prose text.

``REASONING_PROVIDER`` selects the backend (default ``openai``); nothing changes
unless it is explicitly switched.
"""

from __future__ import annotations

import logging
import os

import httpx

from . import config
from .meta_client import get_ssl_context

logger = logging.getLogger(__name__)


def _error(provider: str, err: object) -> str:
    """Build the degradation sentinel callers detect with ``.startswith``."""
    return f"LLM reasoning unavailable ({provider}): {err}"


async def _call_openai(messages: list[dict], system: str, model: str | None) -> str | None:
    """OpenAI chat-completions backend.

    The original httpx logic from ``llm_reasoner`` lives here now. ``system`` is
    folded back into the message list as a leading ``system`` message, which is
    how the chat-completions API expects it.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    resolved = (model or config.openai_model()).strip() or config.openai_model()
    payload_messages: list[dict] = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)
    payload = {"model": resolved, "messages": payload_messages}

    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        return (response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as err:  # noqa: BLE001 - degrade, never raise to the caller
        logger.exception("openai reasoning call failed")
        return _error("openai", err)


async def _call_anthropic(messages: list[dict], system: str, model: str | None) -> str | None:
    """Anthropic Messages API backend.

    Uses the official ``anthropic`` SDK. The (large, reused) persona/knowledge
    system prefix is sent as a cached system block so repeated calls hit the
    prompt cache instead of re-billing the full prefix every turn.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    resolved = (model or config.anthropic_model()).strip() or config.anthropic_model()
    try:
        # Imported lazily so the dependency is only required when this backend is
        # actually selected (keeps the openai/deterministic paths import-light).
        from anthropic import AsyncAnthropic

        system_blocks = (
            [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            if system
            else []
        )

        client = AsyncAnthropic(api_key=api_key, http_client=httpx.AsyncClient(verify=get_ssl_context()))
        try:
            response = await client.messages.create(
                model=resolved,
                max_tokens=4096,
                system=system_blocks,
                messages=messages,
            )
        finally:
            await client.close()

        parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts).strip()
    except Exception as err:  # noqa: BLE001 - degrade, never raise to the caller
        logger.exception("anthropic reasoning call failed")
        return _error("anthropic", err)


async def reason(messages: list[dict], system: str, model: str | None = None) -> str | None:
    """Route a (system, messages) reasoning request to the configured provider.

    Returns ``None`` when the selected provider has no API key, a string
    starting with ``"LLM reasoning unavailable (<provider>): "`` on error, or the
    model's prose otherwise.
    """
    provider = config.reasoning_provider()
    if provider in ("anthropic", "claude"):
        return await _call_anthropic(messages, system, model)
    return await _call_openai(messages, system, model)

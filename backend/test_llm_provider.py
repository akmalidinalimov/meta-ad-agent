"""Tests for the pluggable reasoning seam (backend.llm_provider).

Cover: provider routing via REASONING_PROVIDER, the None-when-key-missing
contract per backend, and the "LLM reasoning unavailable (<provider>): ..."
error string on exception.
"""

from __future__ import annotations

import asyncio

import backend.llm_provider as provider


def _run(coro):
    return asyncio.run(coro)


def test_reason_routes_to_openai_by_default(monkeypatch):
    monkeypatch.delenv("REASONING_PROVIDER", raising=False)
    seen = {}

    async def fake_openai(messages, system, model):
        seen["provider"] = "openai"
        seen["messages"] = messages
        seen["system"] = system
        seen["model"] = model
        return "openai answer"

    async def fake_anthropic(messages, system, model):  # pragma: no cover - must not run
        seen["provider"] = "anthropic"
        return "anthropic answer"

    monkeypatch.setattr(provider, "_call_openai", fake_openai)
    monkeypatch.setattr(provider, "_call_anthropic", fake_anthropic)

    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys", model="m1"))
    assert out == "openai answer"
    assert seen["provider"] == "openai"
    assert seen["system"] == "sys"
    assert seen["model"] == "m1"


def test_reason_routes_to_anthropic_when_selected(monkeypatch):
    monkeypatch.setenv("REASONING_PROVIDER", "anthropic")

    async def fake_openai(messages, system, model):  # pragma: no cover - must not run
        return "openai answer"

    async def fake_anthropic(messages, system, model):
        return "anthropic answer"

    monkeypatch.setattr(provider, "_call_openai", fake_openai)
    monkeypatch.setattr(provider, "_call_anthropic", fake_anthropic)

    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys"))
    assert out == "anthropic answer"


def test_reason_claude_alias_routes_to_anthropic(monkeypatch):
    monkeypatch.setenv("REASONING_PROVIDER", "claude")

    async def fake_anthropic(messages, system, model):
        return "claude answer"

    monkeypatch.setattr(provider, "_call_anthropic", fake_anthropic)
    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys"))
    assert out == "claude answer"


def test_reason_unknown_provider_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("REASONING_PROVIDER", "totally-made-up")

    async def fake_openai(messages, system, model):
        return "openai answer"

    monkeypatch.setattr(provider, "_call_openai", fake_openai)
    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys"))
    assert out == "openai answer"


def test_openai_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = _run(provider._call_openai([{"role": "user", "content": "hi"}], "sys", None))
    assert out is None


def test_anthropic_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = _run(provider._call_anthropic([{"role": "user", "content": "hi"}], "sys", None))
    assert out is None


def test_reason_returns_none_when_selected_provider_key_missing(monkeypatch):
    # Anthropic selected but no ANTHROPIC_API_KEY -> None (deterministic fallback).
    monkeypatch.setenv("REASONING_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys"))
    assert out is None


def test_openai_error_returns_unavailable_string(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise RuntimeError("boom-openai")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(provider.httpx, "AsyncClient", _BoomClient)
    out = _run(provider._call_openai([{"role": "user", "content": "hi"}], "sys", None))
    assert isinstance(out, str)
    assert out.startswith("LLM reasoning unavailable (openai): ")
    assert "boom-openai" in out


def test_anthropic_error_returns_unavailable_string(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    # Force the SDK call to blow up by making the http client constructor raise.
    class _BoomClient:
        def __init__(self, *a, **k):
            raise RuntimeError("boom-anthropic")

    monkeypatch.setattr(provider.httpx, "AsyncClient", _BoomClient)
    out = _run(provider._call_anthropic([{"role": "user", "content": "hi"}], "sys", None))
    assert isinstance(out, str)
    assert out.startswith("LLM reasoning unavailable (anthropic): ")


def test_reason_propagates_error_string_from_backend(monkeypatch):
    monkeypatch.delenv("REASONING_PROVIDER", raising=False)

    async def fake_openai(messages, system, model):
        return "LLM reasoning unavailable (openai): kaboom"

    monkeypatch.setattr(provider, "_call_openai", fake_openai)
    out = _run(provider.reason([{"role": "user", "content": "hi"}], system="sys"))
    assert out.startswith("LLM reasoning unavailable (openai): ")


# --- reasoner wrappers preserve the historical None/unchanged contract --------
# Callers patch the functions on the importing module by name and treat any
# truthy result as the answer to display. The wrappers must therefore convert the
# reason() error sentinel back to None (or to the unchanged text for refine_text)
# so the operator never sees the sentinel.

import backend.llm_reasoner as reasoner  # noqa: E402


def test_chat_answer_normalizes_error_sentinel_to_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_reason(messages, system, model=None):
        return "LLM reasoning unavailable (openai): boom"

    monkeypatch.setattr(reasoner, "reason", fake_reason)
    out = _run(reasoner.generate_chat_answer("q", {"summary": {}}))
    assert out is None


def test_specialist_answer_drops_ungrounded_numbers(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_reason(messages, system, model=None):
        # 4242 is not present in the (empty) context -> hallucination guard trips.
        return "ROAS implies 4242 buyers."

    monkeypatch.setattr(reasoner, "reason", fake_reason)
    out = _run(reasoner.generate_specialist_answer("q", {"summary": {}}, system_prompt="x"))
    assert out is None


def test_refine_text_returns_input_on_error_sentinel(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_reason(messages, system, model=None):
        return "LLM reasoning unavailable (openai): boom"

    monkeypatch.setattr(reasoner, "reason", fake_reason)
    out = _run(reasoner.refine_text("Deterministic with $0.04 CPL.", instruction="improve"))
    assert out == "Deterministic with $0.04 CPL."


def test_reasoner_enabled_gates_on_anthropic_key_when_selected(monkeypatch):
    monkeypatch.setenv("REASONING_PROVIDER", "anthropic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    captured = {}

    async def fake_reason(messages, system, model=None):
        captured["called"] = True
        return "grounded answer"

    monkeypatch.setattr(reasoner, "reason", fake_reason)
    out = _run(reasoner.generate_chat_answer("q", {"summary": {}}))
    assert captured.get("called") is True
    assert out == "grounded answer"

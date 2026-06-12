"""Shared pytest fixtures for the backend suite.

Keeps the suite hermetic and deterministic: the hybrid agent layer only calls
OpenAI when OPENAI_API_KEY is set, so we clear it for every test by default. The
specialist paths then fall back to deterministic templates, which is exactly the
behavior the assertions encode. Tests that want to exercise the LLM path set the
key themselves and mock the HTTP call.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _deterministic_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

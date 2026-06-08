"""Reusable agent chat answer + Telegram HTML formatting.

The dashboard chat endpoint (routers/agents.agent_chat) already routes a free-text
question through the full brain (specialists, council, orchestrator, or the LLM
fallback) and returns a structured answer. The Telegram bot reuses that exact path
so "control by texting" gives the same answers as the web chat. answer_agent_question
is async (the brain awaits LLM calls); answer_agent_question_sync wraps it for the
sync webhook handler (which runs in a threadpool worker, so a fresh event loop is safe).
"""

from __future__ import annotations

import asyncio
import html
import re
from typing import Any

# The output-format directive makes answers use **bold** for the key number/entity.
# Convert that to Telegram <b> (after HTML-escaping) so it renders, not literal **.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def to_telegram_html(text: str) -> str:
    escaped = html.escape(text or "")
    return _BOLD_RE.sub(r"<b>\1</b>", escaped)


async def answer_agent_question(message: str) -> dict[str, Any]:
    # Imported lazily to avoid a router<->service import cycle at module load.
    from .api_models import ChatRequest
    from .routers.agents import agent_chat

    response = await agent_chat(ChatRequest(message=message))
    return {"answer": response.answer, "sources": list(response.sources or [])}


def answer_agent_question_sync(message: str) -> dict[str, Any]:
    return asyncio.run(answer_agent_question(message))

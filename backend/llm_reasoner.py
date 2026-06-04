from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

from .meta_client import get_ssl_context

load_dotenv()

logger = logging.getLogger(__name__)


def _llm_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def _significant_numbers(text: str) -> list[str]:
    """Numbers worth grounding: skip tiny integers (years/percentages like 3, 100)
    that legitimately appear in prose, focus on multi-digit figures that would be
    fabricated metrics (CPL, spend, lead counts)."""
    numbers = []
    for raw in _NUMBER_RE.findall(text):
        normalized = raw.replace(",", "")
        try:
            value = float(normalized)
        except ValueError:
            continue
        if value >= 10 and normalized not in {"100", "1000"}:
            numbers.append(normalized)
    return numbers


def answer_is_grounded(answer: str, context_text: str) -> bool:
    """Hallucination guard: every significant number in the answer must appear in the
    provided context. Prevents the model from inventing a CPL, spend, or lead count
    that is then shown to the operator as if sourced from saved data."""
    haystack = context_text.replace(",", "")
    for number in _significant_numbers(answer):
        if number not in haystack and number.rstrip("0").rstrip(".") not in haystack:
            return False
    return True


async def refine_text(text: str, *, instruction: str, context: Any = None) -> str:
    """Optionally improve deterministic agent output with an LLM.

    Hybrid design: when OPENAI_API_KEY is set, ask the model to sharpen the
    already-correct deterministic text (keeping every number and the
    approval-safety framing). With no key, or on any error, return the text
    unchanged — so behavior is fully deterministic and testable by default.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not text.strip():
        return text

    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You refine a Meta ads agent's analysis. Keep every number and named entity exactly. "
                    "Do not invent data. Never recommend publishing or spending without approval. "
                    "Improve clarity and decisiveness only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{instruction}\n\nDeterministic analysis:\n{text}\n\n"
                    + (f"Structured context:\n{json.dumps(context, ensure_ascii=False)[:8000]}" if context is not None else "")
                ),
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        refined = (response.json()["choices"][0]["message"]["content"] or "").strip()
        return refined or text
    except Exception:
        logger.exception("refine_text failed; returning deterministic text unchanged")
        return text


async def generate_llm_summary(analysis_preview: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    prompt = {
        "role": "user",
        "content": (
            "You are a senior Meta ads strategist for online AI courses. Analyze this Meta ad account summary. "
            "Explain what worked, what did not, recommended audiences, age/gender, country vs region strategy, "
            "placements, interests, creative lessons, and next experiments. Be specific and concise.\n\n"
            f"{json.dumps(analysis_preview, ensure_ascii=False)[:30000]}"
        ),
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a rigorous conversion-focused Meta ads analyst. Do not overclaim; mention when purchase tracking is missing.",
            },
            prompt,
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("generate_llm_summary failed")
        return None


async def generate_chat_answer(question: str, analysis_preview: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the Meta ads audit agent for an online AI course business. "
                    "Answer from the provided saved Meta analysis as your source of truth. "
                    "Be specific, numerical, and conversion-focused. Show formulas when the user asks about calculations. "
                    "For Pixel, visit rate, and landing-page lead rate, use the tracking object and mention whether landing visits are true Pixel landing_page_view events or estimates from link clicks/clicks. "
                    "If landing visits are higher than clicks, explain that Meta action counts are attributed events and can exceed click count because they are not always one-to-one unique click sessions. "
                    "Compare campaigns, ad sets, creatives, audiences, placements, regions, interests, and funnel metrics when relevant. "
                    "Do not give generic marketing advice. Do not repeat a canned answer. "
                    "When purchases are missing or zero, clearly say recommendations are based on lead/click quality, not buyer proof."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    "Saved Meta analysis preview:\n"
                    f"{json.dumps(analysis_preview, ensure_ascii=False)[:30000]}"
                ),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("generate_chat_answer failed")
        return None


async def generate_specialist_answer(
    question: str,
    analysis_preview: dict[str, Any],
    *,
    system_prompt: str,
) -> str | None:
    """Specialist reasoning over the saved analysis using a role-specific persona.

    This is the inverted LLM path: instead of the model being a generic last-resort
    fallback, each specialist reasons with its own system prompt + the house strategy.
    Returns None when no API key is set, on any error, OR when the answer fails the
    hallucination guard — so the caller falls back to the deterministic template and
    the operator never sees an ungrounded number.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    context_text = json.dumps(analysis_preview, ensure_ascii=False)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    "Saved Meta analysis (your only source of truth):\n"
                    f"{context_text[:30000]}"
                ),
            },
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        answer = (response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None

    if not answer or not answer_is_grounded(answer, context_text):
        return None
    return answer

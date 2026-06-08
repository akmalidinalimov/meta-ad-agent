from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from . import config
from .llm_provider import reason

logger = logging.getLogger(__name__)


def _llm_enabled() -> bool:
    """Whether the currently-selected reasoning provider has a usable key.

    Default provider is openai, so with REASONING_PROVIDER unset this is exactly
    the historical ``OPENAI_API_KEY`` check. When switched to anthropic/claude it
    gates on ANTHROPIC_API_KEY instead, so the deterministic fallback still kicks
    in when the active provider has no key.
    """
    if config.reasoning_provider() in ("anthropic", "claude"):
        return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")

# The reasoning seam returns a string starting with this prefix on any backend
# error. The public functions here detect it and degrade to None / the input
# text so the historical contract (None on error, or unchanged text) is kept and
# callers never display the sentinel to the operator.
_UNAVAILABLE_PREFIX = "LLM reasoning unavailable"

# Shared presentation directive appended to chat-facing prompts so answers are
# scannable for a human operator. It only governs FORMAT — the evidence/grounding
# rules in each prompt (and answer_is_grounded) still own factual correctness.
_OUTPUT_FORMAT = (
    "Output format: Lead with the direct answer in 1-2 sentences. Then use short "
    "paragraphs separated by a blank line. Use bullet points (lines starting with "
    "'- ') for any list or ranking. Bold the single key number or entity per point "
    "using **double asterisks**. Keep it tight: no preamble, no filler. Stay strictly "
    "fact-based: use only real numbers from the provided data and never invent a figure "
    "to fill the format."
)


def _usable(result: str | None) -> str | None:
    """Normalize a reason() result to usable prose or None.

    None (no key) and the error sentinel both collapse to None so callers fall
    back to their deterministic templates exactly as before.
    """
    if not result:
        return None
    if result.startswith(_UNAVAILABLE_PREFIX):
        return None
    text = result.strip()
    return text or None


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

    Hybrid design: when a reasoning provider is configured (key present), ask the
    model to sharpen the already-correct deterministic text (keeping every number
    and the approval-safety framing). With no key, or on any error, return the
    text unchanged — so behavior is fully deterministic and testable by default.
    """
    if not _llm_enabled() or not text.strip():
        return text

    system = (
        "You refine a Meta ads agent's analysis. Keep every number and named entity exactly. "
        "Do not invent data. Never recommend publishing or spending without approval. "
        "Improve clarity and decisiveness only."
    )
    user = (
        f"{instruction}\n\nDeterministic analysis:\n{text}\n\n"
        + (
            f"Structured context:\n{json.dumps(context, ensure_ascii=False)[:8000]}"
            if context is not None
            else ""
        )
    )
    result = await reason([{"role": "user", "content": user}], system=system)
    refined = _usable(result)
    return refined or text


async def generate_llm_summary(analysis_preview: dict[str, Any]) -> str | None:
    if not _llm_enabled():
        return None

    system = (
        "You are a rigorous conversion-focused Meta ads analyst. Do not overclaim; mention when purchase tracking is missing. "
        + _OUTPUT_FORMAT
    )
    user = (
        "You are a senior Meta ads strategist for online AI courses. Analyze this Meta ad account summary. "
        "Explain what worked, what did not, recommended audiences, age/gender, country vs region strategy, "
        "placements, interests, creative lessons, and next experiments. Be specific and concise.\n\n"
        f"{json.dumps(analysis_preview, ensure_ascii=False)[:30000]}"
    )
    result = await reason([{"role": "user", "content": user}], system=system)
    return _usable(result)


async def generate_chat_answer(question: str, analysis_preview: dict[str, Any]) -> str | None:
    if not _llm_enabled():
        return None

    system = (
        "You are the Meta ads audit agent for an online AI course business. "
        "Answer from the provided saved Meta analysis as your source of truth. "
        "Be specific, numerical, and conversion-focused. Show formulas when the user asks about calculations. "
        "For Pixel, visit rate, and landing-page lead rate, use the tracking object and mention whether landing visits are true Pixel landing_page_view events or estimates from link clicks/clicks. "
        "If landing visits are higher than clicks, explain that Meta action counts are attributed events and can exceed click count because they are not always one-to-one unique click sessions. "
        "Compare campaigns, ad sets, creatives, audiences, placements, regions, interests, and funnel metrics when relevant. "
        "Do not give generic marketing advice. Do not repeat a canned answer. "
        "When purchases are missing or zero, clearly say recommendations are based on lead/click quality, not buyer proof. "
        + _OUTPUT_FORMAT
    )
    user = (
        f"Question: {question}\n\n"
        "Saved Meta analysis preview:\n"
        f"{json.dumps(analysis_preview, ensure_ascii=False)[:30000]}"
    )
    result = await reason([{"role": "user", "content": user}], system=system)
    return _usable(result)


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
    if not _llm_enabled():
        return None

    context_text = json.dumps(analysis_preview, ensure_ascii=False)
    user = (
        f"Question: {question}\n\n"
        "Saved Meta analysis (your only source of truth):\n"
        f"{context_text[:30000]}"
    )
    result = await reason([{"role": "user", "content": user}], system=system_prompt)
    answer = _usable(result)
    if not answer or not answer_is_grounded(answer, context_text):
        return None
    return answer

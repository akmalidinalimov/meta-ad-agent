from __future__ import annotations

import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

from .meta_client import get_ssl_context

load_dotenv()


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
    except Exception as error:
        return f"LLM summary unavailable: {error}"


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
    except Exception as error:
        return f"LLM chat unavailable: {error}"

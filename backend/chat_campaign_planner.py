from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


DEFAULT_PLACEMENTS = ["instagram_reels", "instagram_stories", "instagram_feed"]
DEFAULT_SECONDARY_METRICS = ["form_button_click", "qualified_lead", "full_payment"]


def can_build_playbook_from_chat(message: str) -> bool:
    lower = message.lower()
    has_campaign_intent = any(token in lower for token in ["create", "launch", "set up", "setup", "campaign", "vsl"])
    has_segment_signal = bool(extract_segment_names(message)) or any(token in lower for token in ["one vsl", "1 vsl", "single vsl"])
    has_budget_signal = extract_budget(message) is not None
    return has_campaign_intent and has_segment_signal and has_budget_signal


def build_playbook_from_chat(message: str, *, knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    budget = extract_budget(message) or 100
    metric = extract_success_metric(message)
    segments = extract_segment_names(message)
    if not segments:
        segments = [infer_single_segment_name(message)]

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"pb_chat_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "name": "Chat campaign plan",
        "goal": "Launch a chat-generated Meta campaign plan and optimize toward downstream buyer quality.",
        "primarySuccessMetric": metric,
        "secondarySuccessMetrics": DEFAULT_SECONDARY_METRICS,
        "segments": [
            build_segment(name, message, budget, knowledge=knowledge)
            for name in segments
        ],
        "rules": {
            "startingBudgetUsd": budget,
            "maxDailyBudgetUsd": max(500, budget * max(1, len(segments)) * 3),
            "scalingStepPercent": 20,
            "scalingFrequencyDays": 1,
            "salesCapacityLeadsPerDay": 200,
            "requiresApprovalForExecution": True,
        },
        "alertChannels": ["dashboard"],
        "approvalChannels": ["dashboard", "telegram"],
        "createdAt": now,
        "updatedAt": now,
    }


def build_segment(name: str, message: str, budget: float, *, knowledge: dict[str, Any] | None) -> dict[str, Any]:
    clean_name = clean_segment_name(name)
    lower = clean_name.lower()
    return {
        "id": slug(clean_name),
        "name": title_segment(clean_name),
        "description": "",
        "vslId": slug(clean_name),
        "landingPageUrl": "",
        "telegramBotUrl": "",
        "targetAudienceNotes": infer_audience_notes(lower),
        "painPoints": infer_pain_points(lower),
        "offerAngle": infer_offer_angle(lower),
        "creativeCountTarget": infer_creative_count(message),
        "startingBudgetUsd": budget,
        "guardrails": [
            "Do not scale from cheap clicks alone.",
            "Prioritize Telegram START and qualified lead quality until CRM purchase data is imported.",
            "Require approval before any live Meta Ads change.",
        ],
        "locations": extract_locations(message),
        "placements": DEFAULT_PLACEMENTS.copy(),
        "interests": infer_interests(lower, knowledge),
        "ageRange": infer_age_range(lower),
        "gender": "all",
    }


def extract_segment_names(message: str) -> list[str]:
    text = message.strip()
    colon_match = re.search(r"(?:vsls?|segments?)\s*:\s*(.+)", text, flags=re.IGNORECASE)
    if colon_match:
        segment_text = colon_match.group(1)
        segment_text = re.split(r"\b(?:start|use|budget|optimi[sz]e|with \$|for \$)\b", segment_text, maxsplit=1, flags=re.IGNORECASE)[0]
        return split_segments(segment_text)

    repeated_vsl_segments = re.findall(
        r"\bone\s+(.+?)\s+vsl\b",
        text,
        flags=re.IGNORECASE,
    )
    if len(repeated_vsl_segments) >= 2:
        return [clean_segment_name(segment) for segment in repeated_vsl_segments if clean_segment_name(segment)]

    count = extract_vsl_count(message)
    if count == 1:
        return [infer_single_segment_name(message)]
    return []


def split_segments(segment_text: str) -> list[str]:
    normalized = segment_text.replace("&", " and ")
    normalized = re.sub(r"\s+and\s+", ",", normalized, flags=re.IGNORECASE)
    parts = [clean_segment_name(part) for part in normalized.split(",")]
    return [part for part in parts if part]


def extract_vsl_count(message: str) -> int | None:
    lower = message.lower()
    if any(token in lower for token in ["one vsl", "1 vsl", "single vsl"]):
        return 1
    match = re.search(r"(\d+)\s*(?:vsls?|segments?)", lower)
    if match:
        return int(match.group(1))
    number_words = {"two": 2, "three": 3, "four": 4, "five": 5}
    for word, value in number_words.items():
        if f"{word} vsl" in lower or f"{word} segment" in lower:
            return value
    return None


def extract_budget(message: str) -> float | None:
    match = re.search(r"\$\s*(\d+(?:\.\d+)?)", message)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:usd|dollars?)", message, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def extract_success_metric(message: str) -> str:
    lower = message.lower()
    if "qualified lead" in lower:
        return "qualified_lead"
    if "full payment" in lower or "purchase" in lower or "paid course" in lower:
        return "full_payment"
    if "form" in lower:
        return "form_button_click"
    if "telegram" in lower or "start" in lower or "bot_start" in lower:
        return "bot_start"
    return "bot_start"


def extract_locations(message: str) -> list[str]:
    lower = message.lower()
    locations = []
    for city in ["Tashkent", "Samarkand", "Fergana", "Andijan", "Bukhara"]:
        if city.lower() in lower:
            locations.append(city)
    if "uzbekistan" in lower or "broad" in lower or not locations:
        return ["Uzbekistan"] if not locations else locations
    return locations


def infer_single_segment_name(message: str) -> str:
    lower = message.lower()
    if "business" in lower or "smm" in lower or "automation" in lower:
        return "small business owners"
    if "creator" in lower or "video editor" in lower:
        return "content creators video editors"
    if "income" in lower or "money" in lower or "earn" in lower:
        return "earning money income"
    return "general ai course audience"


def infer_audience_notes(segment_name: str) -> str:
    if any(token in segment_name for token in ["business", "automation", "agent", "smm", "marketing"]):
        return "Small business owners, SMM/marketing agencies, fashion businesses, and operators with higher purchasing power."
    if any(token in segment_name for token in ["creator", "editor", "video", "content"]):
        return "Content creators and medium-level video editors who can monetize AI videos and improve their portfolio."
    if any(token in segment_name for token in ["income", "money", "earn", "job"]):
        return "Full-time employees and second-income seekers who want to earn with AI and have stronger purchasing power than cheap-volume audiences."
    return "Broad AI-interested audience in Uzbekistan, with quality controlled by creative and Telegram/CRM signals."


def infer_pain_points(segment_name: str) -> list[str]:
    if any(token in segment_name for token in ["business", "automation", "agent", "smm", "marketing"]):
        return ["Need better visuals", "Need automation", "Need higher-value services", "Need content efficiency"]
    if any(token in segment_name for token in ["creator", "editor", "video", "content"]):
        return ["Need eye-catching content", "Need faster editing workflow", "Need portfolio proof", "Need monetization"]
    return ["Need second income", "Uncertainty about earning with AI", "Need practical step-by-step path", "Need trust and proof"]


def infer_offer_angle(segment_name: str) -> str:
    if any(token in segment_name for token in ["business", "automation", "agent", "smm", "marketing"]):
        return "Use AI visuals, commercial videos, and automations to increase business or agency service value."
    if any(token in segment_name for token in ["creator", "editor", "video", "content"]):
        return "Create AI videos, avatars, cartoons, and Instagram portfolio content that can attract paid brand work."
    return "Commercial videos for brands are the clearest AI income path; watch the free video to learn the practical steps."


def infer_interests(segment_name: str, knowledge: dict[str, Any] | None) -> list[str]:
    base: list[str]
    if any(token in segment_name for token in ["business", "automation", "agent", "smm", "marketing"]):
        base = ["Business", "Small business", "Digital marketing", "Marketing services and organizations"]
    elif any(token in segment_name for token in ["creator", "editor", "video", "content"]):
        base = ["Video editing", "Content creation", "Graphic design", "Instagram"]
    else:
        base = ["Artificial intelligence", "Online education", "Freelancing", "Graphic design"]

    ranked = []
    for item in (knowledge or {}).get("analysis", {}).get("audience", {}).get("interests", []):
        label = item.get("label")
        if label:
            ranked.append(str(label))
    return unique(base + ranked[:3])[:6]


def infer_age_range(segment_name: str) -> str:
    if any(token in segment_name for token in ["business", "automation", "agent", "smm", "marketing"]):
        return "25-45"
    if any(token in segment_name for token in ["creator", "editor", "video", "content"]):
        return "20-40"
    return "23-44"


def infer_creative_count(message: str) -> int:
    match = re.search(r"(\d+)\s*(?:creatives?|videos?)", message, flags=re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return 8


def clean_segment_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .;:-")).strip()


def title_segment(value: str) -> str:
    return " ".join(word.capitalize() if word.lower() not in {"ai", "vsl", "smm"} else word.upper() for word in value.split())


def slug(value: str) -> str:
    text = value.lower().replace("/", " ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "segment"


def unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

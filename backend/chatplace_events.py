from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

VISITOR_ID_PATTERN = re.compile(r"\bv_[A-Za-z0-9_-]{3,64}\b")

FIELD_PATHS = {
    "event_name": ["event_name", "eventName", "event", "milestone"],
    "visitor_id": [
        "visitor_id",
        "visitorId",
        "variables.visitor_id",
        "variables.visitorId",
        "start_payload",
        "startPayload",
        "message_text",
        "messageText",
        "message.text",
        "text",
        "trigger",
    ],
    "telegram_user_id": [
        "telegram_user_id",
        "telegramUserId",
        "user_id",
        "userId",
        "client_id",
        "clientId",
        "chat_id",
        "chatId",
        "chatLink",
        "client.id",
        "client.chatLink",
        "user.id",
        "user.chatLink",
        "chat.id",
        "variables.chatLink",
    ],
    "telegram_username": ["telegram_username", "telegramUsername", "username", "client.username", "user.username"],
    "telegram_full_name": [
        "telegram_full_name",
        "telegramFullName",
        "full_name",
        "fullName",
        "client.fullName",
        "user.fullName",
    ],
    "segment": ["segment", "variables.segment"],
    "vsl_id": ["vsl_id", "vslId", "variables.vsl_id", "variables.vslId"],
    "landing_page_id": ["landing_page_id", "landingPageId", "variables.landing_page_id", "variables.landingPageId"],
    "telegram_bot_id": ["telegram_bot_id", "telegramBotId", "variables.telegram_bot_id", "variables.telegramBotId"],
    "campaign_id": ["campaign_id", "campaignId", "variables.campaign_id", "variables.campaignId"],
    "adset_id": ["adset_id", "adSetId", "variables.adset_id", "variables.adSetId"],
    "ad_id": ["ad_id", "adId", "variables.ad_id", "variables.adId"],
    "creative_id": ["creative_id", "creativeId", "variables.creative_id", "variables.creativeId"],
    "utm_source": ["utm_source", "utmSource", "variables.utm_source", "variables.utmSource"],
    "utm_medium": ["utm_medium", "utmMedium", "variables.utm_medium", "variables.utmMedium"],
    "utm_campaign": ["utm_campaign", "utmCampaign", "variables.utm_campaign", "variables.utmCampaign"],
    "utm_content": ["utm_content", "utmContent", "variables.utm_content", "variables.utmContent"],
    "utm_term": ["utm_term", "utmTerm", "variables.utm_term", "variables.utmTerm"],
    "fbclid": ["fbclid", "variables.fbclid"],
}


def normalize_chatplace_event(payload: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {}
    for target, paths in FIELD_PATHS.items():
        value = first_value(payload, paths)
        if target == "visitor_id":
            value = extract_visitor_id(value)
        if value not in (None, ""):
            event[target] = str(value)

    event.setdefault("event_name", "bot_start")
    event["source"] = "chatplace"
    return event


def first_value(payload: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        value = get_path(payload, path)
        if value not in (None, ""):
            return value
    return None


def get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def extract_visitor_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        start_values = parse_qs(parsed.query).get("start")
        if start_values:
            return extract_visitor_id(start_values[0])
    match = VISITOR_ID_PATTERN.search(text)
    if match:
        return match.group(0)
    if text.startswith("/start "):
        return text.split(maxsplit=1)[1][:64]
    return text[:64]

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from .meta_client import get_ssl_context

load_dotenv()


@dataclass(frozen=True)
class BitrixConfig:
    webhook_url: str
    portal_url: str
    user_id: str
    webhook_key: str

    @property
    def is_configured(self) -> bool:
        return bool(build_bitrix_webhook_url(self))


class BitrixTransport(Protocol):
    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        ...


class HttpBitrixTransport:
    def __init__(self, config: BitrixConfig):
        webhook_url = build_bitrix_webhook_url(config)
        if not webhook_url:
            raise ValueError("Bitrix24 webhook URL is not configured.")
        self.webhook_url = webhook_url

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.webhook_url}{method}.json"
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.post(url, json=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Bitrix24 API returned HTTP {response.status_code}.")
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(str(payload.get("error_description") or payload.get("error")))
        return payload


def get_bitrix_config() -> BitrixConfig:
    return BitrixConfig(
        webhook_url=os.getenv("BITRIX24_WEBHOOK_URL", "").strip(),
        portal_url=os.getenv("BITRIX24_PORTAL_URL", "").strip(),
        user_id=os.getenv("BITRIX24_USER_ID", "").strip(),
        webhook_key=os.getenv("BITRIX24_WEBHOOK_KEY", "").strip(),
    )


def build_bitrix_webhook_url(config: BitrixConfig) -> str:
    if config.webhook_url:
        return config.webhook_url if config.webhook_url.endswith("/") else f"{config.webhook_url}/"
    if not (config.portal_url and config.user_id and config.webhook_key):
        return ""
    portal = config.portal_url.rstrip("/")
    return f"{portal}/rest/{config.user_id}/{config.webhook_key}/"


async def fetch_bitrix_leads(*, transport: BitrixTransport, limit: int = 100) -> list[dict[str, Any]]:
    payload = await transport.call(
        "crm.lead.list",
        {
            "order": {"DATE_CREATE": "DESC"},
            "select": ["*", "UF_*"],
            "start": 0,
        },
    )
    rows = payload.get("result", [])
    return [normalize_bitrix_lead(row) for row in rows[:limit]]


def normalize_bitrix_lead(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "crm": "bitrix24",
        "crmLeadId": str(row.get("ID") or ""),
        "title": row.get("TITLE") or "",
        "stage": row.get("STATUS_ID") or row.get("STAGE_ID") or "",
        "source": row.get("SOURCE_ID") or "",
        "phone": first_value(row.get("PHONE")),
        "visitorId": custom_value(row, "UF_CRM_VISITOR_ID", "VISITOR_ID", "visitor_id"),
        "telegramUserId": custom_value(row, "UF_CRM_TELEGRAM_USER_ID", "TELEGRAM_USER_ID", "telegram_user_id"),
        "telegramUsername": custom_value(row, "UF_CRM_TELEGRAM_USERNAME", "TELEGRAM_USERNAME", "telegram_username"),
        "utmSource": row.get("UTM_SOURCE") or "",
        "utmMedium": row.get("UTM_MEDIUM") or "",
        "utmCampaign": row.get("UTM_CAMPAIGN") or "",
        "utmContent": row.get("UTM_CONTENT") or "",
        "utmTerm": row.get("UTM_TERM") or "",
        "createdAt": row.get("DATE_CREATE") or "",
        "updatedAt": row.get("DATE_MODIFY") or "",
        "raw": row,
    }


def first_value(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("VALUE") or "")
    return ""


def custom_value(row: dict[str, Any], *keys: str) -> str:
    lower_map = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = lower_map.get(key.lower())
        if value not in (None, ""):
            return str(value)
    return ""

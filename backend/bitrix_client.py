from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from .meta_client import get_ssl_context

load_dotenv()

TASHKENT_TZ = timezone(timedelta(hours=5))  # Asia/Tashkent (UTC+5, no DST)


def tashkent_day(created_at: Any) -> str:
    """Calendar day of a Bitrix timestamp on **Asia/Tashkent** time.

    Bitrix returns DATE_CREATE with the portal's own offset (currently +03:00 / Moscow), so a raw
    ``[:10]`` buckets leads on Moscow days — misdating the first ~2 late-night Tashkent hours (a real
    traffic peak here) to the previous day. Convert to Tashkent first so lead-days line up with the
    Tashkent spend-day / dashboard window. Unparseable input falls back to the first 10 chars."""
    text = str(created_at or "")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TASHKENT_TZ).date().isoformat()


# Bitrix %TITLE substring that scopes THIS funnel's CRM leads. Default = "AI Creators 5.0" so it
# matches every AI Creators 5.0 variant — the order form ("AI Creators 5.0 buyurtmasi") AND the web
# "Заполнение CRM-формы AI Creators 5.0 | …" forms — but NOT the older "AI Creators 4.0" leads (a
# different product). The exact order-form title alone undercounts (misses the web forms); bare
# "AI Creators" over-counts (pulls in 4.0). Override with BITRIX_LEAD_SOURCE_TITLE.
DEFAULT_LEAD_SOURCE_TITLE = "AI Creators 5.0"


def lead_source_title() -> str:
    return os.getenv("BITRIX_LEAD_SOURCE_TITLE", DEFAULT_LEAD_SOURCE_TITLE).strip()


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


def get_bot_cell_tags() -> tuple[list[str], list[str]]:
    """Markers (from env) that identify Telegram-bot (Cell B) leads in Bitrix:
    SOURCE_DESCRIPTION substrings + utm_content values, comma-separated, with the observed
    live defaults ('Landing B' / 'cellb')."""
    descs = [s.strip() for s in os.getenv("BITRIX_BOT_SOURCE_DESCRIPTION", "Landing B").split(",") if s.strip()]
    utms = [s.strip() for s in os.getenv("BITRIX_BOT_UTM_CONTENT", "cellb").split(",") if s.strip()]
    return descs, utms


def build_bitrix_webhook_url(config: BitrixConfig) -> str:
    if config.webhook_url:
        return config.webhook_url if config.webhook_url.endswith("/") else f"{config.webhook_url}/"
    if not (config.portal_url and config.user_id and config.webhook_key):
        return ""
    portal = config.portal_url.rstrip("/")
    return f"{portal}/rest/{config.user_id}/{config.webhook_key}/"


_MAX_PAGES = 50  # backstop: 50 pages * 50 rows/page = 2500 records per range


def _date_filter(days: int | None) -> dict[str, str] | None:
    if not days:
        return None
    since = (date.today() - timedelta(days=days)).isoformat()
    return {">=DATE_CREATE": since}


async def _fetch_paged(
    *,
    transport: BitrixTransport,
    method: str,
    days: int | None,
    limit: int | None,
    extra_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read-only paged list. Follows Bitrix's ``next`` cursor and merges an optional
    DATE_CREATE filter + an extra filter (e.g. a ``%TITLE`` substring)."""
    filter_ = dict(_date_filter(days) or {})
    if extra_filter:
        filter_.update(extra_filter)
    rows: list[dict[str, Any]] = []
    start = 0
    for _ in range(_MAX_PAGES):
        params: dict[str, Any] = {"order": {"DATE_CREATE": "DESC"}, "select": ["*", "UF_*"], "start": start}
        if filter_:
            params["filter"] = filter_
        payload = await transport.call(method, params)
        batch = payload.get("result", [])
        rows.extend(batch)
        nxt = payload.get("next")
        if not batch or nxt is None:
            break
        if limit is not None and len(rows) >= limit:
            break
        start = nxt
    return rows[:limit] if limit is not None else rows


async def fetch_bitrix_leads(
    *, transport: BitrixTransport, limit: int | None = 100, days: int | None = None, title_contains: str | None = None
) -> list[dict[str, Any]]:
    extra = {"%TITLE": title_contains} if title_contains else None
    rows = await _fetch_paged(transport=transport, method="crm.lead.list", days=days, limit=limit, extra_filter=extra)
    return [normalize_bitrix_lead(row) for row in rows]


async def fetch_bitrix_statuses(*, transport: BitrixTransport, entity_id: str = "STATUS") -> list[dict[str, Any]]:
    payload = await transport.call(
        "crm.status.list",
        {
            "filter": {"ENTITY_ID": entity_id},
            "order": {"SORT": "ASC"},
        },
    )
    rows = payload.get("result", [])
    return [normalize_bitrix_status(row) for row in rows]


def normalize_bitrix_lead(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "crm": "bitrix24",
        "crmLeadId": str(row.get("ID") or ""),
        "title": row.get("TITLE") or "",
        "stage": row.get("STATUS_ID") or row.get("STAGE_ID") or "",
        "source": row.get("SOURCE_ID") or "",
        # SOURCE_DESCRIPTION carries the cell tag (e.g. "Landing B (VSL embed)" for the
        # Telegram-bot VSL form) — the signal that separates bot leads from the same form
        # used elsewhere. See lead_cell() in crm_funnel.
        "sourceDescription": row.get("SOURCE_DESCRIPTION") or "",
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


def normalize_bitrix_status(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("ID") or ""),
        "entityId": str(row.get("ENTITY_ID") or ""),
        "statusId": str(row.get("STATUS_ID") or ""),
        "name": str(row.get("NAME") or row.get("STATUS_ID") or ""),
        "sort": int(as_number(row.get("SORT"))),
    }


def first_value(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("VALUE") or "")
    return ""


def as_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def custom_value(row: dict[str, Any], *keys: str) -> str:
    lower_map = {key.lower(): value for key, value in row.items()}
    for key in keys:
        value = row.get(key)
        if value is None:
            value = lower_map.get(key.lower())
        if value not in (None, ""):
            return str(value)
    return ""

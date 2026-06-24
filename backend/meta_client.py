from __future__ import annotations

import asyncio
import os
import ssl
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import truststore
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class MetaConfig:
    access_token: str
    app_id: str
    ad_account_id: str
    business_id: str
    api_version: str
    pixel_id: str

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id)


class MetaApiError(RuntimeError):
    pass


def get_meta_config() -> MetaConfig:
    return MetaConfig(
        access_token=os.getenv("META_ACCESS_TOKEN", "").strip(),
        app_id=os.getenv("META_APP_ID", "").strip(),
        ad_account_id=normalize_ad_account_id(os.getenv("META_AD_ACCOUNT_ID", "").strip()),
        business_id=os.getenv("META_BUSINESS_ID", "").strip(),
        api_version=os.getenv("META_API_VERSION", "v23.0").strip() or "v23.0",
        pixel_id=os.getenv("META_PIXEL_ID", "").strip(),
    )


def normalize_ad_account_id(value: str) -> str:
    if not value:
        return ""
    return value if value.startswith("act_") else f"act_{value}"


def mask_token(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "********"
    return f"{value[:6]}...{value[-4:]}"


async def get_ad_account_summary(config: MetaConfig) -> dict[str, Any]:
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")

    url = f"https://graph.facebook.com/{config.api_version}/{config.ad_account_id}"
    params = {
        "fields": "id,name,account_status,currency,timezone_name,business_name",
        "access_token": config.access_token,
    }
    add_app_id(config, params)

    try:
        async with httpx.AsyncClient(timeout=20, verify=get_ssl_context()) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    if response.status_code >= 400:
        raise MetaApiError(extract_meta_error(response))

    return response.json()


async def get_campaigns(config: MetaConfig) -> list[dict[str, Any]]:
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")

    url = f"https://graph.facebook.com/{config.api_version}/{config.ad_account_id}/campaigns"
    params = {
        "fields": "id,name,status,effective_status,objective,buying_type,special_ad_categories,bid_strategy,daily_budget,lifetime_budget,start_time,stop_time",
        "limit": 500,
        "access_token": config.access_token,
    }
    add_app_id(config, params)

    try:
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    if response.status_code >= 400:
        raise MetaApiError(extract_meta_error(response))

    return response.json().get("data", [])


async def get_token_permissions(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        "/me/permissions",
        {"limit": 500},
    )


async def get_ad_sets(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        f"/{config.ad_account_id}/adsets",
        {
            "fields": "id,name,campaign_id,status,effective_status,optimization_goal,billing_event,bid_strategy,bid_amount,promoted_object,daily_budget,lifetime_budget,targeting,is_dynamic_creative,start_time,end_time",
            "limit": 500,
        },
    )


async def get_adstudies(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        f"/{config.ad_account_id}/adstudies",
        {
            "fields": "id,name,type,status,start_time,end_time,cells{id,name,treatment_percentage,adsets{id,name,campaign_id}}",
            "limit": 200,
        },
    )


async def get_saved_audiences(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        f"/{config.ad_account_id}/customaudiences",
        {
            "fields": "id,name,subtype,approximate_count_lower_bound,description",
            "limit": 500,
        },
    )


async def get_ads(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        f"/{config.ad_account_id}/ads",
        {
            "fields": "id,name,campaign_id,adset_id,status,effective_status,end_time,creative{id,name,title,body,object_type,thumbnail_url,video_id}",
            "limit": 100,
        },
    )


async def get_ads_for_adset(config: MetaConfig, adset_id: str) -> list[dict[str, Any]]:
    """Fetch the ads of ONE ad set directly (scoped), so the drill-down is complete
    regardless of the account-wide ad page limit."""
    return await paged_get(
        config,
        f"/{adset_id}/ads",
        {
            "fields": (
                "id,name,campaign_id,adset_id,status,effective_status,end_time,"
                "creative{id,name,title,body,object_type,thumbnail_url,image_url,video_id}"
            ),
            "limit": 50,
        },
    )


async def get_adset_ad_insights(
    config: MetaConfig, adset_id: str, *, date_preset: str = "maximum"
) -> list[dict[str, Any]]:
    """Ad-level lifetime performance for ONE ad set, used to rank its creatives.
    Defaults to the `maximum` (lifetime) window so paused/older creatives still
    report spend/impressions/clicks instead of zeros from a 30-day window."""
    return await paged_get(
        config,
        f"/{adset_id}/insights",
        {
            "level": "ad",
            "fields": "ad_id,ad_name,impressions,reach,spend,ctr,clicks,actions",
            "date_preset": date_preset,
            "limit": 200,
        },
    )


async def get_video_source(config: MetaConfig, video_id: str) -> dict[str, Any]:
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")

    url = f"https://graph.facebook.com/{config.api_version}/{video_id}"
    params = {
        "fields": "id,source,picture,permalink_url,thumbnails",
        "access_token": config.access_token,
    }
    add_app_id(config, params)

    try:
        async with httpx.AsyncClient(timeout=20, verify=get_ssl_context()) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    if response.status_code >= 400:
        raise MetaApiError(extract_meta_error(response))

    return response.json()


async def create_campaign(config: MetaConfig, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{config.ad_account_id}/campaigns", payload)


async def create_ad_set(config: MetaConfig, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{config.ad_account_id}/adsets", payload)


async def create_ad(config: MetaConfig, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{config.ad_account_id}/ads", payload)


async def update_campaign(config: MetaConfig, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{campaign_id}", payload)


async def update_ad_set(config: MetaConfig, adset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{adset_id}", payload)


async def update_ad(config: MetaConfig, ad_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{ad_id}", payload)


_INSIGHTS_FIELDS = (
    "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "date_start,date_stop,impressions,reach,frequency,spend,cpm,ctr,cpc,clicks,actions,action_values,"
    # Video engagement for hook-rate / hold-rate creative analysis.
    "video_play_actions,video_thruplay_watched_actions,video_p25_watched_actions,"
    "video_p50_watched_actions,video_p75_watched_actions,video_p100_watched_actions,"
    "video_avg_time_watched_actions"
)


def _insights_params(
    *,
    level: str | None,
    breakdowns: list[str] | None,
    date_preset: str,
    since: date | str | None,
    until: date | str | None,
    time_increment: int | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"fields": _INSIGHTS_FIELDS, "limit": 200}
    if level:
        params["level"] = level
    if time_increment is not None:
        # Per-period rows (default daily). Omit to aggregate over the whole window —
        # much smaller output for ad-hoc breakdown queries.
        params["time_increment"] = time_increment
    if since and until:
        params["time_range"] = f'{{"since":"{since}","until":"{until}"}}'
    else:
        params["date_preset"] = date_preset
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    return params


async def get_insights(
    config: MetaConfig,
    *,
    breakdowns: list[str] | None = None,
    level: str = "ad",
    date_preset: str = "last_90d",
    since: date | str | None = None,
    until: date | str | None = None,
    time_increment: int | None = 1,
) -> list[dict[str, Any]]:
    params = _insights_params(level=level, breakdowns=breakdowns, date_preset=date_preset,
                              since=since, until=until, time_increment=time_increment)
    return await paged_get(config, f"/{config.ad_account_id}/insights", params)


async def get_entity_insights(
    config: MetaConfig,
    object_id: str,
    *,
    breakdowns: list[str] | None = None,
    date_preset: str = "maximum",
    since: date | str | None = None,
    until: date | str | None = None,
    time_increment: int | None = None,
) -> list[dict[str, Any]]:
    """Insights for ONE entity (campaign/adset/ad) via its own endpoint, so a scoped
    breakdown query returns that entity's complete rows instead of being lost in the
    account-wide page cap. `level` is omitted — the entity id determines the scope."""
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")
    params = _insights_params(level=None, breakdowns=breakdowns, date_preset=date_preset,
                              since=since, until=until, time_increment=time_increment)
    return await paged_get(config, f"/{object_id}/insights", params)


async def paged_get(config: MetaConfig, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")

    url = f"https://graph.facebook.com/{config.api_version}{path}"
    request_params = {**params, "access_token": config.access_token}
    add_app_id(config, request_params)
    rows: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            while url:
                response = await _get_with_retry(client, url, request_params)
                request_params = {}
                if response.status_code >= 400:
                    if rows:
                        return rows
                    raise MetaApiError(extract_meta_error(response))
                payload = response.json()
                rows.extend(payload.get("data", []))
                url = payload.get("paging", {}).get("next")
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    return rows


# Transient conditions worth retrying: HTTP 429/5xx and Meta throttling/transient
# error codes (1 unknown, 2 service, 4 app rate limit, 17 user rate limit, 32 page
# rate limit, 341 app limit reached, 613 custom rate limit).
_TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}
_TRANSIENT_META_CODES = {1, 2, 4, 17, 32, 341, 613}


def _is_transient_error(response: httpx.Response) -> bool:
    if response.status_code in _TRANSIENT_HTTP_STATUS:
        return True
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    return error.get("code") in _TRANSIENT_META_CODES


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    max_attempts: int = 4,
    base_delay: float = 0.5,
) -> httpx.Response:
    """GET with exponential backoff on Meta throttling / transient errors.

    A single throttle response used to abort a whole insights breakdown (and silently
    return partial/zero rows); retrying lets the sync ride out short rate-limit windows.
    """
    response = await client.get(url, params=params)
    delay = base_delay
    for _ in range(max_attempts - 1):
        if response.status_code < 400 or not _is_transient_error(response):
            return response
        await asyncio.sleep(delay)
        delay *= 2
        response = await client.get(url, params=params)
    return response


async def post_meta_object(config: MetaConfig, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not config.is_configured:
        raise MetaApiError("Meta access token and ad account ID are required.")

    url = f"https://graph.facebook.com/{config.api_version}{path}"
    request_payload = normalize_write_payload(payload)
    request_payload["access_token"] = config.access_token
    add_app_id(config, request_payload)

    try:
        async with httpx.AsyncClient(timeout=60, verify=get_ssl_context()) as client:
            response = await client.post(url, data=request_payload)
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    if response.status_code >= 400:
        raise MetaApiError(extract_meta_error(response))

    return response.json()


def normalize_write_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            normalized[key] = json_dumps(value)
        elif value is not None:
            normalized[key] = value
    return normalized


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def extract_meta_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Meta API returned HTTP {response.status_code}."

    error = payload.get("error", {})
    message = error.get("message") or "Unknown Meta API error."
    code = error.get("code")
    subcode = error.get("error_subcode")
    # Meta's user-facing fields carry the actionable reason (e.g. which field/value is
    # wrong); surface them so the operator/logs see WHY, not just "Invalid parameter".
    user_title = error.get("error_user_title")
    user_msg = error.get("error_user_msg")
    parts = [message]
    if user_title:
        parts.append(f"- {user_title}")
    if user_msg:
        parts.append(f": {user_msg}")
    if code is not None:
        parts.append(f"(code={code}")
        parts.append(f"subcode={subcode})" if subcode is not None else ")")
    return " ".join(parts)


def get_ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def add_app_id(config: MetaConfig, params: dict[str, Any]) -> None:
    if config.app_id:
        params["app_id"] = config.app_id

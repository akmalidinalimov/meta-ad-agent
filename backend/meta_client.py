from __future__ import annotations

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
        "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time",
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
            "fields": "id,name,campaign_id,status,effective_status,optimization_goal,billing_event,daily_budget,lifetime_budget,targeting,start_time,end_time",
            "limit": 500,
        },
    )


async def get_ads(config: MetaConfig) -> list[dict[str, Any]]:
    return await paged_get(
        config,
        f"/{config.ad_account_id}/ads",
        {
            "fields": "id,name,campaign_id,adset_id,status,effective_status,creative{id,name,title,body,object_type,thumbnail_url,video_id}",
            "limit": 100,
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


async def update_campaign(config: MetaConfig, campaign_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{campaign_id}", payload)


async def update_ad_set(config: MetaConfig, adset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{adset_id}", payload)


async def update_ad(config: MetaConfig, ad_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await post_meta_object(config, f"/{ad_id}", payload)


async def get_insights(
    config: MetaConfig,
    *,
    breakdowns: list[str] | None = None,
    level: str = "ad",
    date_preset: str = "last_90d",
    since: date | str | None = None,
    until: date | str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "level": level,
        "time_increment": 1,
        "fields": (
            "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
            "date_start,date_stop,impressions,reach,frequency,spend,cpm,ctr,cpc,clicks,actions,action_values"
        ),
        "limit": 5000,
    }
    if since and until:
        params["time_range"] = f'{{"since":"{since}","until":"{until}"}}'
    else:
        params["date_preset"] = date_preset
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)

    return await paged_get(config, f"/{config.ad_account_id}/insights", params)


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
                response = await client.get(url, params=request_params)
                request_params = {}
                if response.status_code >= 400:
                    raise MetaApiError(extract_meta_error(response))
                payload = response.json()
                rows.extend(payload.get("data", []))
                url = payload.get("paging", {}).get("next")
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach Meta API: {error}") from error

    return rows


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
    parts = [message]
    if code is not None:
        parts.append(f"code={code}")
    if subcode is not None:
        parts.append(f"subcode={subcode}")
    return " ".join(parts)


def get_ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def add_app_id(config: MetaConfig, params: dict[str, Any]) -> None:
    if config.app_id:
        params["app_id"] = config.app_id

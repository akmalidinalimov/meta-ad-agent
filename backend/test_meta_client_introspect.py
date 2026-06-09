"""Tests for the live-introspection fetchers: get_adstudies / get_saved_audiences,
and the new is_dynamic_creative field on get_ad_sets."""

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

import backend.meta_client as meta_client
from backend.meta_client import (
    MetaApiError,
    MetaConfig,
    get_ad_sets,
    get_adstudies,
    get_saved_audiences,
)


def _configured() -> MetaConfig:
    return MetaConfig(
        access_token="tok",
        app_id="app",
        ad_account_id="act_123",
        business_id="biz",
        api_version="v23.0",
        pixel_id="",
    )


def _install_transport(monkeypatch, handler) -> dict:
    """Route all meta_client httpx traffic through a MockTransport, capturing the
    last request for assertions on path/params."""
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["path"] = request.url.path
        captured["params"] = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        return handler(request)

    transport = httpx.MockTransport(_handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs.pop("verify", None)
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(meta_client.httpx, "AsyncClient", _factory)
    return captured


def test_get_adstudies_hits_path_and_fields(monkeypatch):
    captured = _install_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"data": [{"id": "s1", "name": "AB"}]}),
    )

    result = asyncio.run(get_adstudies(_configured()))

    assert result == [{"id": "s1", "name": "AB"}]
    assert captured["path"] == "/v23.0/act_123/adstudies"
    assert "cells{id,name,treatment_percentage,adsets{id,name,campaign_id}}" in captured["params"]["fields"]
    assert captured["params"]["limit"] == "200"


def test_get_saved_audiences_hits_path_and_fields(monkeypatch):
    captured = _install_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"data": [{"id": "ca1", "name": "Buyers"}]}),
    )

    result = asyncio.run(get_saved_audiences(_configured()))

    assert result == [{"id": "ca1", "name": "Buyers"}]
    assert captured["path"] == "/v23.0/act_123/customaudiences"
    assert "approximate_count_lower_bound" in captured["params"]["fields"]
    assert captured["params"]["limit"] == "500"


def test_get_adstudies_raises_on_4xx(monkeypatch):
    _install_transport(
        monkeypatch,
        lambda req: httpx.Response(403, json={"error": {"message": "missing scope", "code": 200}}),
    )

    with pytest.raises(MetaApiError):
        asyncio.run(get_adstudies(_configured()))


def test_get_saved_audiences_raises_on_4xx(monkeypatch):
    _install_transport(
        monkeypatch,
        lambda req: httpx.Response(400, json={"error": {"message": "bad", "code": 100}}),
    )

    with pytest.raises(MetaApiError):
        asyncio.run(get_saved_audiences(_configured()))


def test_get_ad_sets_fields_include_is_dynamic_creative(monkeypatch):
    captured = _install_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"data": []}),
    )

    asyncio.run(get_ad_sets(_configured()))

    assert "is_dynamic_creative" in captured["params"]["fields"]

import asyncio

import httpx

from backend.meta_client import _get_with_retry, _is_transient_error


def _response(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status, json=body if body is not None else {})


def test_is_transient_error_detects_http_and_meta_codes():
    assert _is_transient_error(_response(429)) is True
    assert _is_transient_error(_response(503)) is True
    assert _is_transient_error(_response(400, {"error": {"code": 17}})) is True  # user rate limit
    assert _is_transient_error(_response(400, {"error": {"code": 100}})) is False  # hard error
    assert _is_transient_error(_response(200)) is False


def test_get_with_retry_retries_then_succeeds():
    calls = {"n": 0}
    sequence = [_response(429), _response(429), _response(200, {"data": []})]

    class FakeClient:
        async def get(self, url, params=None):
            response = sequence[calls["n"]]
            calls["n"] += 1
            return response

    result = asyncio.run(_get_with_retry(FakeClient(), "https://x", {}, base_delay=0))
    assert result.status_code == 200
    assert calls["n"] == 3  # two throttles + one success


def test_get_with_retry_gives_up_after_max_attempts():
    calls = {"n": 0}

    class AlwaysThrottled:
        async def get(self, url, params=None):
            calls["n"] += 1
            return _response(429)

    result = asyncio.run(_get_with_retry(AlwaysThrottled(), "https://x", {}, max_attempts=4, base_delay=0))
    assert result.status_code == 429
    assert calls["n"] == 4  # does not retry forever

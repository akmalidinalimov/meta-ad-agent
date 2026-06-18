from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app

_YT_ENV = [
    "YOUTUBE_API_KEY",
    "YOUTUBE_OAUTH_CLIENT_ID",
    "YOUTUBE_OAUTH_CLIENT_SECRET",
    "YOUTUBE_OAUTH_REFRESH_TOKEN",
    "YOUTUBE_VSL_VIDEO_ID",
]


class FakeVslTransport:
    async def fetch_views(self, video_id):
        return 2000

    async def fetch_retention_rows(self, video_id, days):
        return [(0.0, 1.0), (0.5, 0.175), (1.0, 0.1)]


def _clear(monkeypatch):
    for key in _YT_ENV:
        monkeypatch.delenv(key, raising=False)


def test_vsl_reports_unconfigured_cleanly(monkeypatch):
    _clear(monkeypatch)
    res = TestClient(app).get("/api/vsl")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False and body["ok"] is False
    assert body["views"] is None


def test_vsl_with_oauth_computes_views_and_50pct(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTUBE_VSL_VIDEO_ID", "vid123")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("YOUTUBE_OAUTH_CLIENT_SECRET", "s")
    monkeypatch.setenv("YOUTUBE_OAUTH_REFRESH_TOKEN", "r")
    monkeypatch.setattr(app_module, "build_youtube_transport", lambda config: FakeVslTransport())

    body = TestClient(app).get("/api/vsl?days=30").json()

    assert body["ok"] is True and body["configured"] is True
    assert body["views"] == 2000
    assert body["viewsWatched50"] == 350
    assert body["watchRate50"] == 17.5
    assert body["hasRetention"] is True
    assert body["videoId"] == "vid123"


def test_vsl_data_api_only_shows_views_without_retention(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("YOUTUBE_VSL_VIDEO_ID", "vid123")
    monkeypatch.setenv("YOUTUBE_API_KEY", "key")
    monkeypatch.setattr(app_module, "build_youtube_transport", lambda config: FakeVslTransport())

    body = TestClient(app).get("/api/vsl").json()

    assert body["ok"] is True
    assert body["views"] == 2000
    assert body["viewsWatched50"] is None  # no OAuth -> no retention
    assert body["hasRetention"] is False

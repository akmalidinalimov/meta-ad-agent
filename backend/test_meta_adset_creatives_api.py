from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.adset_creatives as ac
import backend.meta_live as meta_live
import backend.routers.meta as meta_router
from backend.app import app


class _Cfg:
    is_configured = True
    ad_account_id = "act_555"
    api_version = "v23.0"
    pixel_id = ""
    access_token = "tok"


def test_adset_creatives_endpoint_returns_thumbnails_and_stats(monkeypatch):
    monkeypatch.setattr(meta_router, "get_meta_config", lambda: _Cfg())

    async def _fake_fetch(config, adset_id, **kwargs):
        return [
            {
                "id": "ad_1",
                "name": "Hero Video",
                "effective_status": "PAUSED",
                "creative": {"thumbnail_url": "https://x/t.jpg", "title": "Save", "body": "Body", "video_id": "v1", "object_type": "VIDEO"},
                "_perf": {"impressions": 1000, "clicks": 50, "spend": 25.0, "ctr": 5.0, "results": 12, "results_label": "leads", "has_data": True},
            }
        ]

    async def _fake_live(*, knowledge=None, force=False):
        return SimpleNamespace(
            adsets=[{"id": "S1", "name": "Lookalike 1%", "campaign_id": "C1"}],
            campaigns=[{"id": "C1", "name": "Spring Promo"}],
        )

    monkeypatch.setattr(ac, "fetch_adset_creatives", _fake_fetch)
    monkeypatch.setattr(meta_live, "get_live_account", _fake_live)

    client = TestClient(app)
    resp = client.get("/api/meta/adsets/S1/creatives")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["source"] == "live"
    assert body["adsetName"] == "Lookalike 1%"
    assert body["campaignName"] == "Spring Promo"
    assert "act=555" in body["adsManagerUrl"]
    assert len(body["creatives"]) == 1
    c = body["creatives"][0]
    assert c["thumbnailUrl"] == "https://x/t.jpg"
    assert c["videoId"] == "v1"
    assert c["perf"]["clicks"] == 50
    assert c["perf"]["resultsLabel"] == "leads"


def test_adset_creatives_endpoint_unconfigured(monkeypatch):
    # Without Meta creds the endpoint degrades gracefully (no crash, no fetch).
    class _Unconfigured:
        is_configured = False
        ad_account_id = ""

    monkeypatch.setattr(meta_router, "get_meta_config", lambda: _Unconfigured())
    client = TestClient(app)
    resp = client.get("/api/meta/adsets/S1/creatives")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["creatives"] == []

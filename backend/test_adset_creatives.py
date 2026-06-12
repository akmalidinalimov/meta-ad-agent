import backend.adset_creatives as ac


def test_rank_creatives_orders_and_captures_clicks():
    ads = [
        {"id": "a1", "name": "Low"},
        {"id": "a2", "name": "TopResults"},
        {"id": "a3", "name": "HighCtr"},
    ]
    insights = [
        {"ad_id": "a1", "impressions": "100", "clicks": "5", "spend": "1", "ctr": "0.5", "actions": []},
        {"ad_id": "a2", "impressions": "50", "clicks": "9", "spend": "9", "ctr": "1.0",
         "actions": [{"action_type": "offsite_conversion.fb_pixel_lead", "value": "7"}]},
        {"ad_id": "a3", "impressions": "200", "clicks": "40", "spend": "2", "ctr": "5.0", "actions": []},
    ]
    ranked = ac.rank_creatives(ads, insights)
    assert [a["name"] for a in ranked] == ["TopResults", "HighCtr", "Low"]
    assert ranked[0]["_perf"]["results"] == 7
    assert ranked[0]["_perf"]["results_label"] == "leads"
    assert ranked[1]["_perf"]["clicks"] == 40


def test_serialize_creative_shape():
    ad = {
        "id": "ad_1",
        "name": "Hero",
        "effective_status": "PAUSED",
        "creative": {"thumbnail_url": "https://x/t.jpg", "title": "T", "body": "B", "video_id": "v9", "object_type": "VIDEO"},
        "_perf": {"impressions": 12, "clicks": 3, "spend": 4.5, "ctr": 1.2, "results": 2, "results_label": "leads", "has_data": True},
    }
    out = ac.serialize_creative(ad)
    assert out["id"] == "ad_1"
    assert out["status"] == "PAUSED"
    assert out["thumbnailUrl"] == "https://x/t.jpg"
    assert out["videoId"] == "v9"
    assert out["perf"]["clicks"] == 3
    assert out["perf"]["resultsLabel"] == "leads"
    assert out["perf"]["hasData"] is True


def test_fetch_sync_snapshot_fallback_when_not_configured(monkeypatch):
    class _Cfg:
        is_configured = False

    monkeypatch.setattr("backend.meta_client.get_meta_config", lambda: _Cfg())
    monkeypatch.setattr(
        "backend.knowledge_base.load_knowledge_base",
        lambda: {"raw": {"ads": [{"id": "ad_x", "adset_id": "S1", "name": "Snap"}]}},
    )
    ranked, source = ac.fetch_adset_creatives_sync("S1")
    assert source == "snapshot"
    assert [a["name"] for a in ranked] == ["Snap"]
    assert ranked[0]["_perf"]["has_data"] is False

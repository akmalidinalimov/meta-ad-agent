from backend.dashboard_service import map_creative, map_metric_row


def test_map_creative_preserves_meta_attribution_and_media():
    row = {
        "id": "ad_1",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "name": "VID - 08",
        "creative": {
            "id": "creative_meta_1",
            "name": "Creative 1",
            "title": "Proof hook",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "video_id": "video_1",
            "video_url": "https://example.com/video.mp4",
        },
    }

    creative = map_creative(row)

    assert creative["id"] == "creative_meta_1"
    assert creative["adId"] == "ad_1"
    assert creative["campaignId"] == "campaign_1"
    assert creative["adSetId"] == "adset_1"
    assert creative["assetUrl"] == "https://example.com/thumb.jpg"
    assert creative["videoId"] == "video_1"
    assert creative["videoUrl"] == "https://example.com/video.mp4"


def test_map_metric_row_uses_meta_creative_id_when_available():
    row = {
        "date_start": "2026-05-20",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "ad_id": "ad_1",
        "creative_id": "creative_meta_1",
        "publisher_platform": "instagram",
        "platform_position": "reels",
        "spend": "10",
        "impressions": "1000",
        "clicks": "100",
        "actions": [{"action_type": "lead", "value": "7"}],
    }

    metric = map_metric_row(row, 0)

    assert metric["campaignId"] == "campaign_1"
    assert metric["adSetId"] == "adset_1"
    assert metric["adId"] == "ad_1"
    assert metric["creativeId"] == "creative_meta_1"

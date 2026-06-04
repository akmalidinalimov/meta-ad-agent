from backend.analysis_engine import (
    action_count,
    action_value,
    finalize_metrics,
    quality_score,
    summarize_overall,
)
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


def test_action_count_dedupes_overlapping_lead_aliases():
    # Meta reports the SAME lead under several action types. They must not be summed.
    row = {
        "actions": [
            {"action_type": "onsite_web_lead", "value": "120"},
            {"action_type": "lead", "value": "120"},
            {"action_type": "offsite_conversion.fb_pixel_lead", "value": "120"},
        ]
    }
    assert action_count(row, "lead") == 120


def test_map_metric_row_does_not_quadruple_count_leads():
    row = {
        "date_start": "2026-05-20",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "ad_id": "ad_1",
        "spend": "9",
        "impressions": "1000",
        "clicks": "100",
        "actions": [
            {"action_type": "onsite_web_lead", "value": "4442"},
            {"action_type": "lead", "value": "4442"},
            {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4442"},
            {"action_type": "offsite_lead_add_20_s_calls", "value": "4442"},
        ],
    }
    metric = map_metric_row(row, 0)
    assert metric["leads"] == 4442


def test_map_metric_row_populates_purchase_revenue_from_action_values():
    row = {
        "date_start": "2026-05-20",
        "ad_id": "ad_1",
        "spend": "100",
        "impressions": "5000",
        "clicks": "200",
        "actions": [{"action_type": "purchase", "value": "5"}],
        "action_values": [{"action_type": "purchase", "value": "750.50"}],
    }
    metric = map_metric_row(row, 0)
    assert metric["purchases"] == 5
    assert metric["purchaseRevenueUsd"] == 750.50


def test_action_value_reads_purchase_revenue():
    row = {"action_values": [{"action_type": "omni_purchase", "value": "320"}]}
    assert action_value(row, "purchase") == 320


def test_finalize_metrics_computes_roas_aov_cpm_frequency_linkctr():
    item = {
        "spend": 100.0,
        "impressions": 10000.0,
        "reach": 4000.0,
        "clicks": 500.0,
        "linkClicks": 250.0,
        "leads": 50.0,
        "purchases": 4.0,
        "revenue": 400.0,
    }
    finalize_metrics(item)
    assert item["roas"] == 4.0                      # 400 / 100
    assert item["aov"] == 100.0                     # 400 / 4
    assert item["cpm"] == 10.0                      # 100 / 10000 * 1000
    assert item["frequency"] == 2.5                 # 10000 / 4000
    assert item["linkCtr"] == 2.5                   # 250 / 10000 * 100


def test_quality_score_no_longer_dominated_by_lead_rate_and_rewards_volume():
    thin = {"leadRateFromClick": 60.0, "ctr": 2.5, "clicks": 80, "purchases": 0}
    high_volume = {"leadRateFromClick": 60.0, "ctr": 2.5, "clicks": 20000, "purchases": 0}
    # Same rates, but the high-volume segment must outrank the thin one.
    assert quality_score(high_volume) > quality_score(thin)
    # Without purchases, score is capped at the delivery ceiling (<= 70).
    assert quality_score(high_volume) <= 70.0


def test_quality_score_clamps_double_counted_lead_rate():
    # A >100% lead rate (double-count symptom) must not score higher than a clean 100%.
    inflated = {"leadRateFromClick": 250.0, "ctr": 2.5, "clicks": 1000, "purchases": 0}
    clean = {"leadRateFromClick": 100.0, "ctr": 2.5, "clicks": 1000, "purchases": 0}
    assert quality_score(inflated) == quality_score(clean)


def test_finalize_metrics_flags_lead_double_count_risk():
    item = {"clicks": 100.0, "leads": 150.0, "impressions": 1000.0}
    finalize_metrics(item)
    assert item["leadDoubleCountRisk"] is True


def test_finalize_metrics_buyer_economics_with_purchases():
    item = {"spend": 400.0, "clicks": 1000.0, "leads": 100.0, "purchases": 10.0, "impressions": 5000.0}
    finalize_metrics(item)
    assert item["leadToPurchaseCvr"] == 10.0      # 10 / 100 * 100
    assert item["costPerAcquisition"] == 40.0     # 400 / 10
    assert item["cacIsProxy"] is False
    assert item["cacBasis"] == "purchase"


def test_finalize_metrics_buyer_economics_falls_back_to_cpl_proxy():
    item = {"spend": 200.0, "clicks": 1000.0, "leads": 100.0, "purchases": 0.0, "impressions": 5000.0}
    finalize_metrics(item)
    assert item["leadToPurchaseCvr"] is None
    assert item["costPerAcquisition"] == 2.0      # CPL proxy = 200 / 100
    assert item["cacIsProxy"] is True
    assert item["cacBasis"] == "cpl_proxy"


def test_summarize_overall_exposes_buyer_economics_proxy_label():
    rows = [{"spend": "200", "impressions": "5000", "clicks": "1000", "actions": [{"action_type": "lead", "value": "100"}]}]
    summary = summarize_overall(rows)
    assert summary["cacIsProxy"] is True
    assert summary["costPerAcquisition"] == 2.0
    assert summary["leadToPurchaseCvr"] is None


def test_finalize_metrics_computes_hook_and_hold_rate_from_video_fields():
    item = {
        "spend": 100.0,
        "impressions": 10000.0,
        "clicks": 500.0,
        "video3sViews": 3000.0,
        "videoThruplays": 1500.0,
        "videoP25": 2500.0,
        "videoP50": 1800.0,
        "videoP75": 1200.0,
        "videoP100": 900.0,
    }
    finalize_metrics(item)
    assert item["hookRate"] == 30.0          # 3000 / 10000 * 100
    assert item["thruplayRate"] == 15.0      # 1500 / 10000 * 100
    assert item["holdRate"] is not None and 0 < item["holdRate"] < 100


def test_finalize_metrics_leaves_video_rates_none_without_video_fields():
    item = {"spend": 10.0, "impressions": 1000.0, "clicks": 50.0}
    finalize_metrics(item)
    assert item["hookRate"] is None
    assert item["holdRate"] is None


def test_action_count_reads_video_fields_from_top_level_list():
    row = {"video_p25_watched_actions": [{"action_type": "video_p25_watched_actions", "value": "800"}]}
    assert action_count(row, "video_p25") == 800


def test_summarize_overall_exposes_roas_when_revenue_present():
    rows = [
        {
            "spend": "50",
            "impressions": "2000",
            "reach": "1000",
            "clicks": "100",
            "actions": [{"action_type": "purchase", "value": "2"}],
            "action_values": [{"action_type": "purchase", "value": "200"}],
        }
    ]
    summary = summarize_overall(rows)
    assert summary["revenue"] == 200
    assert summary["roas"] == 4.0
    assert summary["aov"] == 100.0

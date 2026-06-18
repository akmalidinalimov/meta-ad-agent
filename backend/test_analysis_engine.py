from backend.analysis_engine import summarize_overall
from backend.app import map_creative, map_metric_row


def _funnel_row(clicks, link_clicks, lpv, leads, subs, campaign_id="campaign_1"):
    return {
        "campaign_id": campaign_id,
        "spend": "10",
        "impressions": "1000",
        "reach": "900",
        "clicks": str(clicks),
        "actions": [
            {"action_type": "link_click", "value": str(link_clicks)},
            {"action_type": "landing_page_view", "value": str(lpv)},
            {"action_type": "lead", "value": str(leads)},
            {"action_type": "subscribe", "value": str(subs)},
        ],
    }


def test_funnel_rates_clean_path():
    totals = summarize_overall([_funnel_row(120, 100, 80, 20, 12)])
    assert totals["linkClicks"] == 100
    assert totals["landingPageViews"] == 80
    assert totals["leads"] == 20
    assert totals["subscribes"] == 12
    assert round(totals["visitRate"], 1) == 80.0   # 80 / 100
    assert round(totals["leadRate"], 1) == 25.0     # 20 / 80
    assert round(totals["startRate"], 1) == 60.0    # 12 / 20


def test_funnel_rates_cap_at_100_on_attribution_overshoot():
    # Landing views can exceed link clicks across attribution windows; never > 100%.
    totals = summarize_overall([_funnel_row(50, 40, 60, 10, 5)])
    assert totals["visitRate"] == 100.0


def test_funnel_rates_aggregate_across_days():
    totals = summarize_overall([_funnel_row(60, 50, 40, 10, 6), _funnel_row(60, 50, 40, 10, 4)])
    assert totals["landingPageViews"] == 80
    assert totals["subscribes"] == 10
    assert round(totals["leadRate"], 1) == 25.0
    assert round(totals["startRate"], 1) == 50.0


def test_funnel_rates_zero_division_is_safe():
    empty = summarize_overall([])
    assert empty["visitRate"] == 0 and empty["leadRate"] == 0 and empty["startRate"] == 0
    no_lpv = summarize_overall([_funnel_row(10, 10, 0, 5, 0)])
    assert no_lpv["leadRate"] == 0


def test_funnel_rates_resolve_pixel_and_capi_aliases():
    row = {
        "clicks": "10",
        "actions": [
            {"action_type": "link_click", "value": "10"},
            {"action_type": "landing_page_view", "value": "8"},
            {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
            {"action_type": "onsite_conversion.subscribe_total", "value": "3"},
        ],
    }
    totals = summarize_overall([row])
    assert totals["leads"] == 4
    assert totals["subscribes"] == 3
    assert round(totals["startRate"], 1) == 75.0


def test_cost_and_ratio_golden_baseline():
    # CHANGE-SAFETY GOLDEN BASELINE: lock the existing cost/ratio outputs so the
    # cost-per-step additions (Phase A2) can prove these never moved. Inputs:
    # spend=10, impressions=1000, clicks=120, link_clicks=100, lpv=80, leads=20, subs=12.
    totals = summarize_overall([_funnel_row(120, 100, 80, 20, 12)])
    assert totals["spend"] == 10
    assert round(totals["ctr"], 4) == 12.0                 # 120 / 1000 * 100
    assert round(totals["cpc"], 4) == round(10 / 120, 4)   # spend / clicks
    assert round(totals["cpl"], 4) == 0.5                  # spend / leads
    assert totals["cpp"] == 0                              # no purchases -> zero-safe
    assert round(totals["leadRateFromClick"], 2) == 16.67  # 20 / 120 * 100


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


def test_map_metric_row_does_not_double_count_meta_lead_aliases():
    row = {
        "date_start": "2026-05-20",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "ad_id": "ad_1",
        "publisher_platform": "instagram",
        "platform_position": "reels",
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

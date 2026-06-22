from backend.audience_creative_metrics import ad_metrics

_ROW = {
    "campaign_id": "c1", "adset_id": "as1", "adset_name": "Lookalike-3%",
    "ad_id": "ad1", "ad_name": "vid_A", "spend": "10", "impressions": "1000",
    "reach": "800", "frequency": "1.25", "clicks": "50", "ctr": "5",
    "actions": [{"action_type": "lead", "value": "20"}],
    "video_play_actions": [{"action_type": "video_view", "value": "400"}],
    "video_p75_watched_actions": [{"action_type": "video_view", "value": "180"}],
    "video_p100_watched_actions": [{"action_type": "video_view", "value": "120"}],
}

def test_ad_metrics_computes_cpl_and_hold_rate():
    m = ad_metrics(_ROW, conversion_event="LEAD")
    assert m["adId"] == "ad1" and m["adName"] == "vid_A"
    assert m["spend"] == 10.0 and m["leads"] == 20
    assert m["cpl"] == 0.5                      # 10 / 20
    assert m["frequency"] == 1.25
    assert round(m["holdRate"], 2) == 0.45      # p75 180 / video_plays 400
    assert m["hasVideo"] is True

def test_ad_metrics_zero_leads_is_safe():
    row = {**_ROW, "actions": []}
    m = ad_metrics(row, conversion_event="LEAD")
    assert m["leads"] == 0 and m["cpl"] is None  # no division by zero

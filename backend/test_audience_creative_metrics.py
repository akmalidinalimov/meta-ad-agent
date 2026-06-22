from backend.audience_creative_metrics import ad_metrics, aggregate_adsets, account_norms, quality_score, rank_creatives, FLOORS

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


# ---------------------------------------------------------------------------
# Task 2 — Per-audience aggregation + account norms
# ---------------------------------------------------------------------------

_ADS = [
    {"campaign_id": "c1", "adset_id": "as1", "adset_name": "LAL", "ad_id": "a", "ad_name": "v1",
     "spend": "10", "impressions": "1000", "frequency": "1.2", "ctr": "5",
     "actions": [{"action_type": "lead", "value": "20"}],
     "video_play_actions": [{"action_type": "video_view", "value": "400"}],
     "video_p75_watched_actions": [{"action_type": "video_view", "value": "200"}]},
    {"campaign_id": "c1", "adset_id": "as1", "adset_name": "LAL", "ad_id": "b", "ad_name": "v2",
     "spend": "6", "impressions": "600", "frequency": "1.1", "ctr": "3",
     "actions": [{"action_type": "lead", "value": "4"}]},
    {"campaign_id": "c1", "adset_id": "as2", "adset_name": "Interest", "ad_id": "c", "ad_name": "v3",
     "spend": "8", "impressions": "900", "frequency": "1.0", "ctr": "2",
     "actions": [{"action_type": "lead", "value": "16"}]},
]

def test_aggregate_adsets_sums_per_audience():
    rows = aggregate_adsets(_ADS, conversion_event="LEAD")
    by_id = {r["adsetId"]: r for r in rows}
    assert by_id["as1"]["spend"] == 16.0 and by_id["as1"]["leads"] == 24
    assert by_id["as1"]["cpl"] == round(16 / 24, 2)
    assert by_id["as1"]["adCount"] == 2

def test_account_norms_uses_medians():
    rows = aggregate_adsets(_ADS, conversion_event="LEAD")
    norms = account_norms(rows)
    assert norms["medianCtr"] > 0 and norms["medianCpl"] > 0


# ---------------------------------------------------------------------------
# Task 3 — Proxy quality score + creative ranking/flags
# ---------------------------------------------------------------------------

def test_quality_score_rewards_engagement_depth():
    norms = {"medianCtr": 3.0, "medianCpl": 0.6, "medianHold": 0.3}
    deep = {"ctr": 4.0, "frequency": 1.1, "holdRate": 0.45, "startRate": 80.0}
    shallow = {"ctr": 4.0, "frequency": 1.1, "holdRate": 0.10, "startRate": 80.0}
    assert quality_score(deep, norms, account_start_rate=70.0) > quality_score(shallow, norms, account_start_rate=70.0)
    assert 0 <= quality_score(shallow, norms, account_start_rate=70.0) <= 100

def test_rank_creatives_flags_zero_result_spender():
    ads = [
        {"adId": "good", "adName": "v1", "spend": 8.0, "impressions": 900, "leads": 16, "cpl": 0.5,
         "ctr": 4.0, "frequency": 1.2, "holdRate": 0.4, "hasVideo": True},
        {"adId": "dead", "adName": "v9", "spend": 6.0, "impressions": 800, "leads": 0, "cpl": None,
         "ctr": 0.5, "frequency": 4.2, "holdRate": 0.05, "hasVideo": True},
    ]
    ranked = rank_creatives(ads, norms={"medianCtr": 3.0, "medianCpl": 0.6, "medianHold": 0.3})
    assert ranked["top"][0]["adId"] == "good"
    dead = next(a for a in ranked["all"] if a["adId"] == "dead")
    assert "zero_result" in dead["flags"] and "fatigue" in dead["flags"]

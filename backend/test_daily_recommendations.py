from backend.daily_recommendations import recommend, LEARNING_CONVERSIONS, detect_anomalies


def _audiences():
    return [
        {"adsetId": "as1", "adsetName": "LAL", "leads": 60, "cpl": 0.55, "quality": 78,
         "creatives": {"all": [{"adId": "dead", "adName": "v9", "leads": 0, "spend": 6.0,
                                "impressions": 900, "flags": ["zero_result", "fatigue"]}]}},
        {"adsetId": "as2", "adsetName": "Interest", "leads": 80, "cpl": 0.40, "quality": 45,
         "creatives": {"all": []}},
    ]


def test_learning_phase_prefers_leave_and_test():
    recs = recommend(_audiences(), total_conversions=20, targets={})  # < 50 -> learning
    assert any(r["action"] == "leave_and_test" for r in recs)
    assert all(r["action"] != "pause_creative" for r in recs)  # no cuts while learning


def test_mature_campaign_recommends_quality_priority_and_pause():
    recs = recommend(_audiences(), total_conversions=200, targets={})
    actions = {r["action"] for r in recs}
    assert "prioritize_audience" in actions          # LAL: higher quality even if pricier
    assert "downweight_audience" in actions           # Interest: cheap but low quality
    assert "pause_creative" in actions                # dead creative past the floor
    prioritize = next(r for r in recs if r["action"] == "prioritize_audience")
    assert prioritize["target"] == "as1" and prioritize["goalLink"]


def test_detect_anomalies_flags_cpl_spike_and_zero_result_spend():
    today = {"cpl": 1.6, "spend": 40.0, "leads": 25}
    baseline = {"cpl": 0.6}                       # 1.6 vs 0.6 -> >2x spike
    alerts = detect_anomalies(today, baseline, targets={"maxCpl": 0.8})
    kinds = {a["kind"] for a in alerts}
    assert "cpl_spike" in kinds and "cpl_over_target" in kinds


def test_detect_anomalies_zero_result_burn():
    alerts = detect_anomalies({"cpl": None, "spend": 25.0, "leads": 0}, {"cpl": 0.6}, targets={})
    assert any(a["kind"] == "zero_result_spend" for a in alerts)


def test_detect_anomalies_quiet_when_healthy():
    assert detect_anomalies({"cpl": 0.55, "spend": 30.0, "leads": 55}, {"cpl": 0.6}, targets={"maxCpl": 0.8}) == []

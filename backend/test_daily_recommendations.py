from backend.daily_recommendations import recommend, LEARNING_CONVERSIONS


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

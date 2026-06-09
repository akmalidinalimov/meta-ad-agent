from backend.campaign_specific_analysis import campaign_roster_answer

KB = {
    "raw": {
        "campaigns": [
            {"id": "1", "name": "Webinar A", "status": "ACTIVE", "objective": "OUTCOME_LEADS", "daily_budget": "10000"},
            {"id": "2", "name": "Retarget B", "status": "PAUSED", "objective": "OUTCOME_SALES"},
            {"id": "3", "name": "Promo C", "status": "ACTIVE"},
        ]
    }
}


def test_roster_lists_active_campaigns_only():
    out = campaign_roster_answer("what campaigns are active?", KB)
    assert out is not None
    assert "Webinar A" in out and "Promo C" in out
    assert "Retarget B" not in out
    assert "2 active, 1 paused" in out.replace("**", "")
    assert "$100/day" in out  # 10000 cents -> $100/day


def test_roster_paused_only():
    out = campaign_roster_answer("show paused campaigns", KB)
    assert out is not None and "Retarget B" in out and "Webinar A" not in out


def test_roster_all_when_unspecified():
    out = campaign_roster_answer("list my campaigns", KB)
    assert out and all(name in out for name in ("Webinar A", "Retarget B", "Promo C"))


def test_roster_none_for_unrelated_question():
    assert campaign_roster_answer("which audience should I scale?", KB) is None


def test_roster_none_without_campaigns():
    assert campaign_roster_answer("what campaigns are active?", {"raw": {"campaigns": []}}) is None

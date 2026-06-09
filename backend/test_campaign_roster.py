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


LIVE_CAMPAIGNS = [
    {"id": "10", "name": "Live Active", "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS"},
    {"id": "11", "name": "Live Paused", "effective_status": "PAUSED"},
]


def test_roster_uses_passed_live_campaigns_with_no_footer():
    out = campaign_roster_answer("what campaigns are active?", {}, campaigns=LIVE_CAMPAIGNS, source="live")
    assert out is not None
    assert "Live Active" in out
    assert "Live Paused" not in out
    assert "1 active, 1 paused" in out.replace("**", "")
    assert "live Meta data was unavailable" not in out


def test_roster_snapshot_source_appends_footer():
    out = campaign_roster_answer("what campaigns are active?", {}, campaigns=LIVE_CAMPAIGNS, source="snapshot")
    assert out is not None
    assert "Live Active" in out
    assert out.endswith("_As of last sync; live Meta data was unavailable._")


def test_roster_passed_campaigns_override_knowledge():
    out = campaign_roster_answer("list my campaigns", KB, campaigns=LIVE_CAMPAIGNS, source="live")
    assert out is not None
    assert "Live Active" in out and "Live Paused" in out
    assert "Webinar A" not in out

from backend.chat_campaign_planner import build_playbook_from_chat, can_build_playbook_from_chat
from backend.test_strategy_generator import sample_knowledge


def test_can_build_playbook_from_chat_detects_real_campaign_brief():
    assert can_build_playbook_from_chat(
        "Create a campaign with three VSLs: earning money, business automation, content creators. Use $100 each."
    )
    assert not can_build_playbook_from_chat("Set up my next campaign")


def test_build_playbook_from_chat_extracts_segments_budget_and_metric():
    playbook = build_playbook_from_chat(
        (
            "Create a campaign with 3 VSLs: earning money / income, productivity for businesses automation agents, "
            "and content creators video editors. Start $100 each, optimize for Telegram START, Uzbekistan broad."
        ),
        knowledge=sample_knowledge(),
    )

    assert playbook["name"] == "Chat campaign plan"
    assert playbook["primarySuccessMetric"] == "bot_start"
    assert playbook["rules"]["startingBudgetUsd"] == 100
    assert len(playbook["segments"]) == 3
    assert [segment["id"] for segment in playbook["segments"]] == [
        "earning_money_income",
        "productivity_for_businesses_automation_agents",
        "content_creators_video_editors",
    ]
    assert all(segment["startingBudgetUsd"] == 100 for segment in playbook["segments"])
    assert all(segment["locations"] == ["Uzbekistan"] for segment in playbook["segments"])
    assert all(segment["placements"] == ["instagram_reels", "instagram_stories", "instagram_feed"] for segment in playbook["segments"])
    assert "Commercial videos for brands" in playbook["segments"][0]["offerAngle"]
    assert "business" in playbook["segments"][1]["targetAudienceNotes"].lower()
    assert "video editors" in playbook["segments"][2]["targetAudienceNotes"].lower()


def test_build_playbook_from_chat_supports_single_vsl_and_custom_budget():
    playbook = build_playbook_from_chat(
        "Launch one VSL for small business owners in Tashkent with $200 per day and qualified lead as the success metric.",
        knowledge=sample_knowledge(),
    )

    assert len(playbook["segments"]) == 1
    assert playbook["primarySuccessMetric"] == "qualified_lead"
    assert playbook["rules"]["startingBudgetUsd"] == 200
    assert playbook["segments"][0]["locations"] == ["Tashkent"]
    assert playbook["segments"][0]["startingBudgetUsd"] == 200

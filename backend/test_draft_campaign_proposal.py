from backend.draft_campaign_proposal import build_draft_campaign_proposal
from backend.test_strategy_generator import sample_knowledge, sample_playbook
from fastapi.testclient import TestClient

from backend.app import app


def test_build_draft_campaign_proposal_is_review_only_and_uses_historical_evidence():
    proposal = build_draft_campaign_proposal(sample_playbook(), sample_knowledge(), account_id="act_123")

    assert proposal["mode"] == "review_only"
    assert proposal["requiresApproval"] is True
    assert proposal["publishBlocked"] is True
    assert proposal["draftCampaign"]["status"] == "PAUSED"
    assert proposal["draftCampaign"]["name"].endswith(" - DRAFT")
    assert proposal["recommendedAudiences"][0]["segmentName"] == "AI income"
    # Per-audience creative plan is surfaced additively, one block per proposed segment.
    creatives = proposal["recommendedCreatives"]
    assert [block["segment"] for block in creatives] == ["AI income", "Business automation"]
    assert all(len(block["newAngleBriefs"]) >= 2 for block in creatives)
    assert "instagram_reels" in proposal["recommendedPlacements"]
    assert "facebook_feed" in proposal["avoidPlacements"]
    assert proposal["budgetPlan"]["totalDailyBudgetUsd"] == 250
    assert proposal["approvalPacket"]["status"] in {"needs_review", "blocked"}
    assert proposal["approvalPacket"]["after"]["adsets"][0]["status"] == "PAUSED"
    assert proposal["operatorChecklist"][0].lower().startswith("confirm")


def test_build_draft_campaign_proposal_surfaces_missing_tracking_before_execution():
    playbook = sample_playbook()
    for segment in playbook["segments"]:
        segment.pop("landingPageUrl", None)
        segment.pop("telegramBotUrl", None)

    proposal = build_draft_campaign_proposal(playbook, sample_knowledge(), account_id="act_123")

    assert proposal["trackingReadiness"]["status"] == "needs_links"
    assert "landing_page" in proposal["trackingReadiness"]["missing"][0]["missing"]
    assert any("visitor_id" in item.lower() for item in proposal["operatorChecklist"])


def _knowledge_with_template_and_audiences():
    knowledge = sample_knowledge()
    knowledge["analysis"]["topCampaigns"] = [
        {
            "label": "Winning VSL",
            "keys": {"campaign_id": "cmp_win", "campaign_name": "Winning VSL"},
            "config": {
                "objective": "OUTCOME_SALES",
                "buyingType": "AUCTION",
                "specialAdCategories": [],
                "budgetMode": "CBO",
                "optimizationGoal": "OFFSITE_CONVERSIONS",
                "billingEvent": "IMPRESSIONS",
                "bidStrategy": "COST_CAP",
                "promotedObjectPixelId": "pixel_win",
            },
        }
    ]
    return knowledge


def test_draft_proposal_includes_top_three_audiences_excluding_recently_tested():
    proposal = build_draft_campaign_proposal(
        sample_playbook(), _knowledge_with_template_and_audiences(), account_id="act_123"
    )
    top_three = proposal["recommendedAudiencesTopThree"]
    assert len(top_three["audiences"]) <= 3
    # sample_playbook segments already use these interests -> excluded from suggestions.
    suggested = {a["label"] for a in top_three["audiences"]}
    assert "Graphic design" not in suggested  # used by the business segment
    assert "Artificial intelligence" not in suggested  # used by the income segment
    assert "Graphic design" in top_three["excludedRecentlyTested"]


def test_draft_proposal_mirrors_winning_campaign_config_into_template():
    proposal = build_draft_campaign_proposal(
        sample_playbook(), _knowledge_with_template_and_audiences(), account_id="act_123"
    )
    source = proposal["sourceTemplate"]
    assert source["sourceCampaignId"] == "cmp_win"
    assert source["sourceCampaignName"] == "Winning VSL"
    assert source["config"]["objective"] == "OUTCOME_SALES"
    # The mirrored config threads into the draft campaign + ad sets. A CBO winner
    # still yields an ABO draft (budget sharing OFF) so the paused campaign is a
    # valid Meta write and each test audience keeps its own budget.
    assert proposal["draftCampaign"]["objective"] == "OUTCOME_SALES"
    assert proposal["draftCampaign"]["is_adset_budget_sharing_enabled"] is False
    assert proposal["draftCampaign"]["status"] == "PAUSED"
    adset = proposal["draftAdSets"][0]
    assert adset["bid_strategy"] == "COST_CAP"
    # Template pixel drives OFFSITE_CONVERSIONS optimization on the ad set.
    assert adset["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert adset["promoted_object"]["pixel_id"] == "pixel_win"


def test_draft_proposal_without_template_keeps_live_valid_defaults():
    # No topCampaigns config -> sourceTemplate is None and defaults are preserved.
    proposal = build_draft_campaign_proposal(sample_playbook(), sample_knowledge(), account_id="act_123")
    assert proposal["sourceTemplate"] is None
    assert proposal["draftCampaign"]["objective"] == "OUTCOME_LEADS"
    assert proposal["draftCampaign"]["is_adset_budget_sharing_enabled"] is False
    assert "_templateSource" not in proposal["draftCampaign"]


def test_draft_campaign_proposal_api_returns_review_packet_without_saving_approval():
    client = TestClient(app)

    response = client.post(
        "/api/campaign-proposals/draft",
        json={"playbook": sample_playbook(), "accountId": "act_123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["proposal"]["mode"] == "review_only"
    assert payload["proposal"]["approvalPacket"]["status"] in {"needs_review", "blocked"}
    assert payload["proposal"]["draftCampaign"]["status"] == "PAUSED"

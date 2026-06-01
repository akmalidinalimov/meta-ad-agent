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

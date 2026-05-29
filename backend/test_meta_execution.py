from backend.meta_execution import (
    build_campaign_creation_approval,
    execute_campaign_creation_approval,
)
from backend.test_strategy_generator import sample_playbook


def test_build_campaign_creation_approval_creates_paused_api_payloads():
    request = build_campaign_creation_approval(
        sample_playbook(),
        account_id="act_123",
        reason="Use cheapest audience clusters from 90-day analysis.",
    )

    assert request["actionType"] == "create_paused_campaign_structure"
    assert request["status"] == "needs_review"
    assert request["requiresApproval"] is True
    assert request["executionMethod"] == "api"
    assert request["guardrailResult"] == "warn"
    assert request["target"] == {"level": "ad_account", "id": "act_123", "name": "act_123"}
    assert request["after"]["campaign"]["status"] == "PAUSED"
    assert request["after"]["campaign"]["objective"] == "OUTCOME_LEADS"
    assert request["after"]["campaign"]["special_ad_categories"] == []
    assert len(request["after"]["adsets"]) == 2
    assert all(adset["status"] == "PAUSED" for adset in request["after"]["adsets"])
    assert all(adset["targeting"]["publisher_platforms"] == ["instagram"] for adset in request["after"]["adsets"])


def test_campaign_creation_approval_fails_budget_guardrail_when_total_budget_is_too_high():
    playbook = sample_playbook()
    playbook["rules"]["maxDailyBudgetUsd"] = 100

    request = build_campaign_creation_approval(playbook, account_id="act_123")

    assert request["guardrailResult"] == "fail"
    assert "above max daily budget" in request["guardrailChecks"][0]["message"].lower()
    assert request["status"] == "blocked"


def test_execute_campaign_creation_dry_run_never_calls_meta():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")
    request["status"] = "approved"

    result = execute_campaign_creation_approval(request, dry_run=True)

    assert result["ok"] is True
    assert result["dryRun"] is True
    assert result["created"] == []
    assert result["wouldCreate"]["campaign"]["status"] == "PAUSED"


def test_execute_campaign_creation_blocks_without_approval():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")

    result = execute_campaign_creation_approval(request, dry_run=True)

    assert result["ok"] is False
    assert "approval" in result["error"].lower()

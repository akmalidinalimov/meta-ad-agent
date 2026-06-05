import asyncio

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
    assert request["operationPreview"]["publishBlocked"] is True
    assert request["operationPreview"]["liveSpendRisk"] == "none_while_paused"
    assert request["operationPreview"]["steps"][0].startswith("Create PAUSED campaign")
    assert request["executionReadiness"]["canExecuteNow"] is False
    assert "approval" in request["executionReadiness"]["blockedBy"]


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

    result = asyncio.run(execute_campaign_creation_approval(request, dry_run=True))

    assert result["ok"] is True
    assert result["dryRun"] is True
    assert result["created"] == []
    assert result["wouldCreate"]["campaign"]["status"] == "PAUSED"


def test_execute_campaign_creation_blocks_without_approval():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")

    result = asyncio.run(execute_campaign_creation_approval(request, dry_run=True))

    assert result["ok"] is False
    assert "approval" in result["error"].lower()


def test_execute_campaign_creation_blocks_live_writes_when_disabled():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")
    request["status"] = "approved"

    result = asyncio.run(
        execute_campaign_creation_approval(
            request,
            dry_run=False,
            confirm_live=True,
            live_writes_enabled=False,
        )
    )

    assert result["ok"] is False
    assert "disabled" in result["error"].lower()


def test_execute_campaign_creation_requires_final_live_confirmation():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")
    request["status"] = "approved"

    result = asyncio.run(
        execute_campaign_creation_approval(
            request,
            dry_run=False,
            live_writes_enabled=True,
        )
    )

    assert result["ok"] is False
    assert "confirm" in result["error"].lower()


def test_execute_campaign_creation_calls_meta_creators_with_paused_payloads():
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")
    request["status"] = "approved"
    calls = []

    async def create_campaign(payload):
        calls.append(("campaign", payload))
        return {"id": "cmp_123", "status": payload["status"]}

    async def create_ad_set(payload):
        calls.append(("adset", payload))
        return {"id": f"as_{len(calls)}", "status": payload["status"]}

    result = asyncio.run(
        execute_campaign_creation_approval(
            request,
            dry_run=False,
            confirm_live=True,
            live_writes_enabled=True,
            create_campaign=create_campaign,
            create_ad_set=create_ad_set,
        )
    )

    assert result["ok"] is True
    assert result["dryRun"] is False
    assert result["created"][0] == {"level": "campaign", "id": "cmp_123", "name": "June AI course launch - DRAFT"}
    assert len([call for call in calls if call[0] == "adset"]) == 2
    assert all(call[1]["status"] == "PAUSED" for call in calls)
    assert all(call[1].get("campaign_id") == "cmp_123" for call in calls if call[0] == "adset")


def _knowledge_with_creatives():
    return {
        "analysis": {
            "topAds": [
                {"label": "VID - 24", "creative": {"id": "26274347335541753"}},
                {"label": "VID - 22", "creative": {"id": "953285077179242"}},
            ]
        }
    }


def test_approval_attaches_winning_creatives_as_paused_ads_from_knowledge():
    request = build_campaign_creation_approval(
        sample_playbook(),
        account_id="act_123",
        knowledge=_knowledge_with_creatives(),
    )
    adsets = request["after"]["adsets"]
    # One winning creative attached per ad set, cycling the pool.
    assert adsets[0]["ads"][0]["creativeId"] == "26274347335541753"
    assert adsets[1]["ads"][0]["creativeId"] == "953285077179242"
    assert all(ad["status"] == "PAUSED" for adset in adsets for ad in adset["ads"])
    assert any("Create PAUSED ad" in step for step in request["operationPreview"]["steps"])


def test_execute_creates_paused_ads_reusing_creative_ids():
    request = build_campaign_creation_approval(
        sample_playbook(),
        account_id="act_123",
        knowledge=_knowledge_with_creatives(),
    )
    request["status"] = "approved"
    created_ads = []

    async def create_campaign(payload):
        return {"id": "cmp_123"}

    async def create_ad_set(payload):
        # The packet-only `ads` key must never be sent to Meta's ad-set endpoint.
        assert "ads" not in payload
        return {"id": "as_1"}

    async def create_ad(payload):
        created_ads.append(payload)
        assert payload["status"] == "PAUSED"
        assert "creative_id" in payload["creative"]
        return {"id": f"ad_{len(created_ads)}"}

    result = asyncio.run(
        execute_campaign_creation_approval(
            request,
            dry_run=False,
            confirm_live=True,
            live_writes_enabled=True,
            create_campaign=create_campaign,
            create_ad_set=create_ad_set,
            create_ad=create_ad,
        )
    )

    assert result["ok"] is True
    ad_results = [item for item in result["created"] if item["level"] == "ad"]
    assert len(ad_results) == 2
    assert {ad["creative"]["creative_id"] for ad in created_ads} == {"26274347335541753", "953285077179242"}

import asyncio

from backend.meta_execution import (
    build_ad_payloads,
    build_adset_payload,
    build_campaign_creation_approval,
    build_campaign_payload,
    execute_campaign_creation_approval,
    extract_top_creatives,
)
from backend.test_strategy_generator import sample_playbook


def test_adset_payload_is_live_valid_with_pixel():
    segment = {"name": "Income", "locations": ["Uzbekistan"], "ageRange": "20-45"}
    payload = build_adset_payload(segment, sample_playbook(), pixel_id="123456789")
    assert payload["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert payload["promoted_object"] == {"pixel_id": "123456789", "custom_event_type": "COMPLETE_REGISTRATION"}
    assert payload["destination_type"] == "WEBSITE"
    assert payload["targeting"]["publisher_platforms"] == ["instagram"]
    # Name-only interest targeting is omitted (Meta rejects flexible_spec without real IDs).
    assert "flexible_spec" not in payload["targeting"]


def test_adset_payload_falls_back_to_link_clicks_without_pixel():
    payload = build_adset_payload({"name": "Seg"}, sample_playbook())
    assert payload["optimization_goal"] == "LINK_CLICKS"
    assert "promoted_object" not in payload


def _winning_template():
    return {
        "objective": "OUTCOME_SALES",
        "buyingType": "AUCTION",
        "specialAdCategories": [],
        "budgetMode": "CBO",
        "optimizationGoal": "OFFSITE_CONVERSIONS",
        "billingEvent": "LINK_CLICKS",
        "bidStrategy": "COST_CAP",
        "promotedObjectPixelId": "pixel_999",
    }


def test_campaign_payload_without_template_is_unchanged_live_valid_shape():
    # Lock the live-validated default shape: with no template the output must be exactly this.
    payload = build_campaign_payload(sample_playbook())
    assert payload == {
        "name": "June AI course launch - DRAFT",
        "objective": "OUTCOME_LEADS",
        "status": "PAUSED",
        "special_ad_categories": [],
        "buying_type": "AUCTION",
        "is_adset_budget_sharing_enabled": False,
    }
    # Passing template=None must be byte-identical to passing nothing.
    assert build_campaign_payload(sample_playbook(), template=None) == payload


def test_adset_payload_without_template_is_unchanged_live_valid_shape():
    segment = {"name": "Income", "locations": ["Uzbekistan"], "ageRange": "20-45"}
    base = build_adset_payload(segment, sample_playbook(), pixel_id="123456789")
    # template=None must reproduce the exact prior live-valid output.
    assert build_adset_payload(segment, sample_playbook(), pixel_id="123456789", template=None) == base
    assert "_templateSource" not in base
    # No-pixel default path is also unchanged.
    no_pixel = build_adset_payload({"name": "Seg"}, sample_playbook())
    assert build_adset_payload({"name": "Seg"}, sample_playbook(), template=None) == no_pixel


def test_campaign_payload_inherits_objective_and_budget_mode_from_template():
    payload = build_campaign_payload(sample_playbook(), template=_winning_template())
    assert payload["objective"] == "OUTCOME_SALES"
    assert payload["buying_type"] == "AUCTION"
    # Even a CBO winner produces an ABO test draft: ad-set budget sharing stays OFF so the
    # paused campaign is a valid Meta write (sharing needs a campaign budget + bid strategy
    # we don't set) and each test audience keeps its own budget.
    assert payload["is_adset_budget_sharing_enabled"] is False
    assert payload["_templateSource"] == "mirrored_from_winning_campaign_config"
    assert payload["status"] == "PAUSED"


def test_adset_payload_inherits_optimization_billing_and_bid_from_template():
    segment = {"name": "Income", "locations": ["Uzbekistan"], "ageRange": "20-45"}
    # Template carries a pixel, so its optimization goal is mirrored too.
    payload = build_adset_payload(segment, sample_playbook(), template=_winning_template())
    assert payload["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert payload["promoted_object"]["pixel_id"] == "pixel_999"
    assert payload["billing_event"] == "LINK_CLICKS"
    assert payload["bid_strategy"] == "COST_CAP"
    assert payload["_templateSource"] == "mirrored_from_winning_campaign_config"
    assert payload["status"] == "PAUSED"


def test_adset_template_without_pixel_keeps_validatable_goal():
    # A template with no pixel must NOT mirror an OFFSITE_CONVERSIONS goal (would fail
    # Graph validation with no promoted_object); it still inherits billing/bid only.
    template = {**_winning_template(), "promotedObjectPixelId": None}
    payload = build_adset_payload({"name": "Seg"}, sample_playbook(), template=template)
    assert payload["optimization_goal"] == "LINK_CLICKS"
    assert "promoted_object" not in payload
    assert payload["bid_strategy"] == "COST_CAP"


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
    assert request["after"]["campaign"]["is_adset_budget_sharing_enabled"] is False
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


def test_execute_strips_template_metadata_before_meta_write():
    request = build_campaign_creation_approval(
        sample_playbook(), account_id="act_123", template=_winning_template()
    )
    request["status"] = "approved"
    sent = []

    async def create_campaign(payload):
        sent.append(("campaign", payload))
        return {"id": "cmp_1"}

    async def create_ad_set(payload):
        sent.append(("adset", payload))
        return {"id": "as_1"}

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
    # No underscore-prefixed packet metadata may reach the Meta create functions.
    for _, payload in sent:
        assert not any(str(key).startswith("_") for key in payload)


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
    # Each ad set leads with the top creatives (default limit 3; pool here has 2), so
    # every audience is tested against the account's best assets.
    assert [ad["creativeId"] for ad in adsets[0]["ads"]] == ["26274347335541753", "953285077179242"]
    assert [ad["creativeId"] for ad in adsets[1]["ads"]] == ["26274347335541753", "953285077179242"]
    assert all(ad["status"] == "PAUSED" for adset in adsets for ad in adset["ads"])
    assert any("Create PAUSED ad" in step for step in request["operationPreview"]["steps"])


def test_extract_top_creatives_respects_limit():
    knowledge = {
        "analysis": {
            "topAds": [
                {"label": f"VID-{i}", "creative": {"id": f"c{i}"}} for i in range(8)
            ]
        }
    }
    assert len(extract_top_creatives(knowledge)) == 3
    five = extract_top_creatives(knowledge, limit=5)
    assert [c["creativeId"] for c in five] == ["c0", "c1", "c2", "c3", "c4"]


def test_build_ad_payloads_default_limit_is_byte_identical_for_single_pool():
    # Live-valid lock: with the default limit and a single-creative pool, an ad set still
    # produces exactly the one PAUSED ad it always did.
    segment = {"name": "Income"}
    pool = [{"creativeId": "c1", "name": "Winner"}]
    assert build_ad_payloads(segment, pool, 0) == [
        {"name": "Winner - Income", "creativeId": "c1", "status": "PAUSED"}
    ]


def test_build_campaign_creation_approval_attaches_five_creatives_per_adset():
    knowledge = {
        "analysis": {
            "topAds": [
                {"label": f"VID-{i}", "creative": {"id": f"c{i}"}} for i in range(6)
            ]
        }
    }
    request = build_campaign_creation_approval(
        sample_playbook(),
        account_id="act_123",
        knowledge=knowledge,
        creatives_limit=5,
    )
    adsets = request["after"]["adsets"]
    for adset in adsets:
        assert len(adset["ads"]) == 5
        assert [ad["creativeId"] for ad in adset["ads"]] == ["c0", "c1", "c2", "c3", "c4"]
        assert all(ad["status"] == "PAUSED" for ad in adset["ads"])


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
    # Two ad sets, each leading with the top creatives (pool of 2) -> 4 paused ads.
    assert len(ad_results) == 4
    assert {ad["creative"]["creative_id"] for ad in created_ads} == {"26274347335541753", "953285077179242"}

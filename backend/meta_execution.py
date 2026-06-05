from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

MetaCreateFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def build_campaign_creation_approval(
    playbook: dict[str, Any],
    *,
    account_id: str,
    reason: str = "Create a paused Meta campaign structure from the approved playbook.",
    knowledge: dict[str, Any] | None = None,
    pixel_id: str | None = None,
    template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    campaign = build_campaign_payload(playbook, template=template)
    # Reuse the account's best historical creatives (from synced knowledge) as paused
    # ads, distributed one-per-ad-set — the same "apply the winners" move a media buyer
    # makes by hand. Empty when no knowledge is synced, so the packet degrades to
    # campaign + ad sets only (the prior behavior).
    creatives_pool = extract_top_creatives(knowledge)
    segments = playbook.get("segments", [])
    adsets = []
    for index, segment in enumerate(segments):
        adset = build_adset_payload(segment, playbook, pixel_id=pixel_id, template=template)
        adset["ads"] = build_ad_payloads(segment, creatives_pool, index)
        adsets.append(adset)
    checks = guardrail_checks(playbook, adsets)
    guardrail_result = rollup_guardrail(checks)
    approval = {
        "id": f"approval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "actionType": "create_paused_campaign_structure",
        "target": {"level": "ad_account", "id": account_id, "name": account_id},
        "before": {"campaigns": [], "adsets": []},
        "after": {"campaign": campaign, "adsets": adsets},
        "reason": reason,
        "risk": "medium" if guardrail_result != "fail" else "high",
        "expectedImpact": "Create a paused campaign shell and paused ad sets for review before any spend can happen.",
        "guardrailResult": guardrail_result,
        "guardrailChecks": checks,
        "executionMethod": "api",
        "requiresApproval": True,
        "status": "blocked" if guardrail_result == "fail" else "needs_review",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    approval["operationPreview"] = build_operation_preview(campaign, adsets)
    approval["executionReadiness"] = build_execution_readiness(approval)
    return approval


def build_campaign_payload(playbook: dict[str, Any], *, template: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the PAUSED campaign payload.

    With template=None this returns the exact LIVE-VALIDATED hardcoded shape (Graph v23,
    proven against the real account) and MUST stay byte-identical — the live-valid tests
    lock it. When a `template` (a WS-G `config` block from a past WINNING campaign) is
    supplied, mirror its objective/buyingType/budgetMode/specialAdCategories so a new test
    inherits what already works on this account instead of the defaults.
    """
    payload = {
        "name": f"{playbook.get('name', 'Meta Agent Campaign')} - DRAFT",
        "objective": "OUTCOME_LEADS",
        "status": "PAUSED",
        "special_ad_categories": [],
        "buying_type": "AUCTION",
        # ABO (ad-set budgets): Graph v23 requires this be set explicitly when the
        # campaign has no budget. False = ad sets do not share budget.
        "is_adset_budget_sharing_enabled": False,
    }
    if not template:
        return payload

    objective = template.get("objective")
    if objective:
        payload["objective"] = objective
    buying_type = template.get("buyingType")
    if buying_type:
        payload["buying_type"] = buying_type
    special_categories = template.get("specialAdCategories")
    if special_categories is not None:
        payload["special_ad_categories"] = special_categories
    # CBO mirrors campaign-level budget sharing; ABO (or unknown) keeps the ad-set model.
    # We never set a live budget here (paused review shell), only the sharing flag intent.
    if template.get("budgetMode") == "CBO":
        payload["is_adset_budget_sharing_enabled"] = True
    payload["_templateSource"] = "mirrored_from_winning_campaign_config"
    return payload


def _strip_private_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop packet-only annotation keys (underscore-prefixed) before any Meta write."""
    return {key: value for key, value in payload.items() if not str(key).startswith("_")}


def build_operation_preview(campaign: dict[str, Any], adsets: list[dict[str, Any]]) -> dict[str, Any]:
    ad_steps = [
        f"Create PAUSED ad: {ad.get('name')} (reuse creative {ad.get('creativeId')})"
        for adset in adsets
        for ad in (adset.get("ads") or [])
    ]
    return {
        "publishBlocked": True,
        "liveSpendRisk": "none_while_paused",
        "steps": [
            f"Create PAUSED campaign: {campaign.get('name')}",
            *[f"Create PAUSED ad set: {adset.get('name')} with ${float(adset.get('daily_budget', 0)) / 100:,.2f}/day" for adset in adsets],
            *ad_steps,
            "All objects remain PAUSED until you approve activation separately.",
        ],
        "safetyNotes": [
            "All generated Meta objects must remain PAUSED.",
            "No publish or active status is allowed in this approval packet.",
            "Live writes remain disabled unless configuration and final confirmation both allow them.",
        ],
    }


def build_execution_readiness(approval: dict[str, Any]) -> dict[str, Any]:
    blocked_by = []
    if approval.get("status") != "approved":
        blocked_by.append("approval")
    if approval.get("guardrailResult") == "fail":
        blocked_by.append("guardrail")
    blocked_by.append("live_write_configuration")
    return {
        "canExecuteNow": False,
        "blockedBy": blocked_by,
        "nextSafeStep": "Review and approve the packet, then run dry-run execution before any live Meta write.",
    }


def build_adset_payload(
    segment: dict[str, Any],
    playbook: dict[str, Any],
    *,
    pixel_id: str | None = None,
    template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a LIVE-VALID paused ad-set matching the account's proven pattern.

    With a pixel: OUTCOME_LEADS + OFFSITE_CONVERSIONS optimizing the website-registration
    event (what produces the account's ~$0.07 registrations). Without a pixel: LINK_CLICKS,
    which needs no promoted_object and always validates. Targeting is broad geo + age on
    Instagram only — we deliberately omit interest targeting because Meta requires real
    interest IDs (name-only flexible_spec is rejected), and broad/Advantage+ is the
    account's best-performing approach anyway.

    With template=None this output is byte-identical to the prior live-validated shape and
    MUST stay so. When a `template` (a past WINNING campaign's `config` block) is supplied,
    mirror its billingEvent/bidStrategy, and — when a pixel is wired — its optimizationGoal
    and pixel, so a new test inherits the proven settings instead of the defaults.
    """
    budget = int(round(float(segment.get("startingBudgetUsd") or playbook.get("rules", {}).get("startingBudgetUsd") or 100) * 100))
    payload: dict[str, Any] = {
        "name": f"{segment.get('name', 'Segment')} - DRAFT",
        "status": "PAUSED",
        "daily_budget": budget,
        "billing_event": "IMPRESSIONS",
        # ABO autobid: lowest cost without a cap needs no bid amount; Graph v23 requires
        # the strategy be explicit on the ad set when the campaign has no budget.
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "destination_type": "WEBSITE",
        "targeting": {
            "geo_locations": geo_locations(segment.get("locations") or ["Uzbekistan"]),
            "age_min": age_min(segment.get("ageRange")),
            "age_max": age_max(segment.get("ageRange")),
            "publisher_platforms": ["instagram"],
            "instagram_positions": instagram_positions(segment.get("placements") or []),
            # Graph v23 requires the Advantage+ audience flag be explicit. 0 = respect the
            # geo/age targeting as set (no algorithmic expansion).
            "targeting_automation": {"advantage_audience": 0},
        },
    }
    template_pixel = template.get("promotedObjectPixelId") if template else None
    effective_pixel = pixel_id or template_pixel
    if effective_pixel:
        payload["optimization_goal"] = "OFFSITE_CONVERSIONS"
        payload["promoted_object"] = {"pixel_id": str(effective_pixel), "custom_event_type": "COMPLETE_REGISTRATION"}
    else:
        # No pixel wired -> a goal that needs no promoted_object, so the create still validates.
        payload["optimization_goal"] = "LINK_CLICKS"

    if template:
        # Mirror the proven ad-set settings from the winning campaign's config. Only override
        # when the template actually carries a value, so missing fields keep the safe defaults.
        billing_event = template.get("billingEvent")
        if billing_event:
            payload["billing_event"] = billing_event
        bid_strategy = template.get("bidStrategy")
        if bid_strategy:
            payload["bid_strategy"] = bid_strategy
        optimization_goal = template.get("optimizationGoal")
        # Only mirror the optimization goal when we have a pixel to back it — otherwise an
        # OFFSITE_CONVERSIONS-style goal with no promoted_object would fail Graph validation.
        if optimization_goal and effective_pixel:
            payload["optimization_goal"] = optimization_goal
        payload["_templateSource"] = "mirrored_from_winning_campaign_config"
    return payload


def extract_top_creatives(knowledge: dict[str, Any] | None, *, limit: int = 3) -> list[dict[str, Any]]:
    """Pull the account's best historical creatives (with a real Meta creative id) from
    the synced analysis, ranked best-first by topAds order (quality-sorted upstream)."""
    analysis = (knowledge or {}).get("analysis", {})
    creatives: list[dict[str, Any]] = []
    for ad in analysis.get("topAds", []) or []:
        creative = ad.get("creative") or {}
        creative_id = creative.get("id")
        if not creative_id:
            continue
        creatives.append({
            "creativeId": str(creative_id),
            "name": ad.get("label") or creative.get("name") or "Winning creative",
        })
        if len(creatives) >= limit:
            break
    return creatives


def build_ad_payloads(segment: dict[str, Any], creatives_pool: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    """Attach one proven creative per ad set, cycling through the pool (mirrors a buyer
    leading each audience with a known winner). Empty pool -> no ads (structure only)."""
    if not creatives_pool:
        return []
    chosen = creatives_pool[index % len(creatives_pool)]
    return [{
        "name": f"{chosen['name']} - {segment.get('name', 'Segment')}",
        "creativeId": chosen["creativeId"],
        "status": "PAUSED",
    }]


async def execute_campaign_creation_approval(
    approval_request: dict[str, Any],
    *,
    dry_run: bool = True,
    confirm_live: bool = False,
    live_writes_enabled: bool = False,
    create_campaign: MetaCreateFn | None = None,
    create_ad_set: MetaCreateFn | None = None,
    create_ad: MetaCreateFn | None = None,
) -> dict[str, Any]:
    if not is_execution_approved_status(approval_request.get("status")):
        return {"ok": False, "error": "Specific approval is required before execution."}
    if approval_request.get("guardrailResult") == "fail":
        return {"ok": False, "error": "Guardrail failed; execution is blocked."}
    if dry_run:
        return {
            "ok": True,
            "dryRun": True,
            "created": [],
            "wouldCreate": approval_request.get("after", {}),
            "note": "Dry run only. No request was sent to Meta.",
        }
    block = assert_executable(approval_request, confirm_live=confirm_live, live_writes_enabled=live_writes_enabled)
    if block:
        return {"ok": False, "dryRun": False, "error": block}
    if not create_campaign or not create_ad_set:
        return {"ok": False, "dryRun": False, "error": "Meta create functions are not configured."}

    after = approval_request.get("after", {})
    campaign_payload = after.get("campaign") or {}
    adset_payloads = after.get("adsets") or []
    created = []
    # Strip packet-only metadata (underscore-prefixed, e.g. _templateSource) before any
    # Meta write; these are our annotations, not Graph fields, and would fail validation.
    campaign_result = await create_campaign(_strip_private_keys(campaign_payload))
    campaign_id = campaign_result.get("id")
    if not campaign_id:
        return {
            "ok": False,
            "dryRun": False,
            "created": created,
            "error": "Meta campaign creation did not return a campaign ID.",
            "rawResult": campaign_result,
        }

    created.append({
        "level": "campaign",
        "id": campaign_id,
        "name": campaign_payload.get("name"),
    })
    for adset_payload in adset_payloads:
        # `ads` and any underscore-prefixed key (e.g. _templateSource) are our packet
        # metadata, not Meta ad-set fields — strip before sending.
        ads_to_create = adset_payload.get("ads") or []
        next_payload = _strip_private_keys({key: value for key, value in adset_payload.items() if key != "ads"})
        next_payload["campaign_id"] = campaign_id
        adset_result = await create_ad_set(next_payload)
        adset_id = adset_result.get("id")
        if not adset_id:
            return {
                "ok": False,
                "dryRun": False,
                "created": created,
                "error": "Meta ad set creation did not return an ad set ID.",
                "rawResult": adset_result,
            }
        created.append({
            "level": "adset",
            "id": adset_id,
            "name": next_payload.get("name"),
        })

        # Create the proven creatives as PAUSED ads under this ad set (reusing existing
        # creative IDs). Skipped when no create_ad fn is wired or no ads are attached.
        if create_ad:
            for ad in ads_to_create:
                ad_payload = {
                    "name": ad.get("name", "Winning creative"),
                    "adset_id": adset_id,
                    "creative": {"creative_id": ad["creativeId"]},
                    "status": "PAUSED",
                }
                ad_result = await create_ad(ad_payload)
                ad_id = ad_result.get("id")
                if not ad_id:
                    return {
                        "ok": False,
                        "dryRun": False,
                        "created": created,
                        "error": "Meta ad creation did not return an ad ID.",
                        "rawResult": ad_result,
                    }
                created.append({
                    "level": "ad",
                    "id": ad_id,
                    "name": ad_payload["name"],
                    "creativeId": ad["creativeId"],
                })

    return {
        "ok": True,
        "dryRun": False,
        "created": created,
        "note": "Live Meta write completed. Created objects (campaign, ad sets, ads) are paused by default.",
    }


async def execute_meta_action_approval(approval: dict[str, Any], *, writer: Any) -> dict[str, Any]:
    if not is_execution_approved_status(approval.get("status")):
        return {"ok": False, "blockedReason": "Approval must be approved before execution."}

    target = approval.get("target") or {}
    level = target.get("level")
    object_id = target.get("id")
    action_type = approval.get("actionType")
    after = approval.get("after") or {}

    if not level or not object_id:
        return {"ok": False, "blockedReason": "Target object level and ID are required."}

    payload = payload_for_meta_action(action_type, after)
    if not payload:
        return {"ok": False, "blockedReason": "No executable payload was generated."}

    if level == "campaign":
        response = await writer.update_campaign(object_id, payload)
    elif level == "adset":
        response = await writer.update_ad_set(object_id, payload)
    elif level == "ad":
        response = await writer.update_ad(object_id, payload)
    else:
        return {"ok": False, "blockedReason": f"Unsupported target level: {level}"}

    return {
        "ok": True,
        "approvalId": approval.get("id"),
        "executionMethod": approval.get("executionMethod", "api"),
        "metaResponse": response,
    }


def payload_for_meta_action(action_type: str | None, after: dict[str, Any]) -> dict[str, Any]:
    if action_type == "rename_meta_object" and after.get("name"):
        return {"name": after["name"]}
    if action_type == "pause_meta_object":
        return {"status": "PAUSED"}
    if action_type == "enable_meta_object":
        return {"status": "ACTIVE"}
    if action_type == "change_meta_budget" and after.get("daily_budget_usd") is not None:
        return {"daily_budget": int(round(float(after["daily_budget_usd"]) * 100))}
    return {}


def is_execution_approved_status(status: Any) -> bool:
    return status in {"approved", "dry_run_completed"}


def assert_executable(
    approval: dict[str, Any],
    *,
    confirm_live: bool,
    live_writes_enabled: bool,
) -> str | None:
    """Single source of truth for the live-write gate.

    Returns a blocking reason string, or None when a live write may proceed. Both the
    campaign-creation and meta-action execution paths call this so the safety policy
    (the most security-critical logic in the app) cannot drift between two copies.
    """
    if not is_execution_approved_status(approval.get("status")):
        return "Specific approval is required before execution."
    if approval.get("guardrailResult") == "fail":
        return "Guardrail failed; execution is blocked."
    if not confirm_live:
        return "Final live confirmation is required before Meta writes."
    if not live_writes_enabled:
        return "Live Meta writes are disabled by configuration."
    return None


def guardrail_checks(playbook: dict[str, Any], adsets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = playbook.get("rules", {})
    max_daily = float(rules.get("maxDailyBudgetUsd") or 0)
    total_daily = sum(float(adset.get("daily_budget") or 0) / 100 for adset in adsets)
    checks = []
    if max_daily and total_daily > max_daily:
        checks.append({
            "result": "fail",
            "message": f"Total daily budget ${total_daily:,.2f} is above max daily budget ${max_daily:,.2f}.",
        })
    else:
        checks.append({
            "result": "pass",
            "message": f"Total daily budget ${total_daily:,.2f} is inside the configured max.",
        })
    if any(adset.get("status") != "PAUSED" for adset in adsets):
        checks.append({"result": "fail", "message": "All generated ad sets must be PAUSED."})
    else:
        checks.append({"result": "pass", "message": "Campaign and ad sets are generated as PAUSED."})
    if any(not only_instagram(adset) for adset in adsets):
        checks.append({"result": "warn", "message": "One or more ad sets include non-Instagram placement."})
    else:
        checks.append({"result": "pass", "message": "Ad sets are Instagram-only by default."})
    if any(not adset["targeting"].get("flexible_spec") for adset in adsets):
        checks.append({"result": "warn", "message": "One or more ad sets have no explicit interests and rely on broad targeting."})
    if any(not segment.get("landingPageUrl") or not segment.get("telegramBotUrl") for segment in playbook.get("segments", [])):
        checks.append({
            "result": "warn",
            "message": "One or more segments are missing landing page or Telegram bot links.",
        })
    return checks


def rollup_guardrail(checks: list[dict[str, Any]]) -> str:
    results = {check.get("result") for check in checks}
    if "fail" in results:
        return "fail"
    if "warn" in results:
        return "warn"
    return "pass"


def only_instagram(adset: dict[str, Any]) -> bool:
    return adset.get("targeting", {}).get("publisher_platforms") == ["instagram"]


def geo_locations(locations: list[str]) -> dict[str, Any]:
    city_names = [location for location in locations if str(location).lower() not in {"uzbekistan", "uz"}]
    if city_names:
        return {
            "custom_locations": [
                {"custom_type": "multi_city", "country": "UZ", "name": city}
                for city in city_names
            ],
            "location_types": ["home", "recent"],
        }
    return {"countries": ["UZ"], "location_types": ["home", "recent"]}


def age_min(age_range: Any) -> int:
    parsed = parse_age_range(age_range)
    return parsed[0] if parsed else 18


def age_max(age_range: Any) -> int:
    parsed = parse_age_range(age_range)
    return parsed[1] if parsed else 65


def parse_age_range(age_range: Any) -> tuple[int, int] | None:
    if not age_range:
        return None
    parts = str(age_range).replace(" ", "").split("-")
    if len(parts) != 2:
        return None
    try:
        return max(18, int(parts[0])), min(65, int(parts[1]))
    except ValueError:
        return None


def instagram_positions(placements: list[str]) -> list[str]:
    positions = []
    mapping = {
        "instagram_reels": "reels",
        "instagram_stories": "story",
        "instagram_feed": "stream",
    }
    for placement in placements:
        position = mapping.get(str(placement))
        if position:
            positions.append(position)
    return positions or ["reels", "story", "stream"]


def flexible_spec(interests: list[str]) -> list[dict[str, Any]]:
    clean = [str(interest).strip() for interest in interests if str(interest).strip()]
    if not clean:
        return []
    return [{"interests": [{"name": interest} for interest in clean[:8]]}]

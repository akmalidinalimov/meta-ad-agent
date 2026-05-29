from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_campaign_creation_approval(
    playbook: dict[str, Any],
    *,
    account_id: str,
    reason: str = "Create a paused Meta campaign structure from the approved playbook.",
) -> dict[str, Any]:
    campaign = build_campaign_payload(playbook)
    adsets = [build_adset_payload(segment, playbook) for segment in playbook.get("segments", [])]
    checks = guardrail_checks(playbook, adsets)
    guardrail_result = rollup_guardrail(checks)
    return {
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


def build_campaign_payload(playbook: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": f"{playbook.get('name', 'Meta Agent Campaign')} - DRAFT",
        "objective": "OUTCOME_LEADS",
        "status": "PAUSED",
        "special_ad_categories": [],
        "buying_type": "AUCTION",
    }


def build_adset_payload(segment: dict[str, Any], playbook: dict[str, Any]) -> dict[str, Any]:
    budget = int(round(float(segment.get("startingBudgetUsd") or playbook.get("rules", {}).get("startingBudgetUsd") or 100) * 100))
    return {
        "name": f"{segment.get('name', 'Segment')} - DRAFT",
        "status": "PAUSED",
        "daily_budget": budget,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LEAD_GENERATION",
        "targeting": {
            "geo_locations": geo_locations(segment.get("locations") or ["Uzbekistan"]),
            "age_min": age_min(segment.get("ageRange")),
            "age_max": age_max(segment.get("ageRange")),
            "publisher_platforms": ["instagram"],
            "instagram_positions": instagram_positions(segment.get("placements") or []),
            "flexible_spec": flexible_spec(segment.get("interests") or []),
        },
    }


def execute_campaign_creation_approval(
    approval_request: dict[str, Any],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    if approval_request.get("status") != "approved":
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
    return {
        "ok": False,
        "dryRun": False,
        "error": "Live Meta writes are not enabled in this build. Use dry run until the final execution confirmation endpoint is implemented.",
    }


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

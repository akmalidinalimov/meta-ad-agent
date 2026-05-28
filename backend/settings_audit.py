from __future__ import annotations

from collections import Counter
from typing import Any


def build_settings_audit(raw: dict[str, Any]) -> dict[str, Any]:
    campaigns = [campaign for campaign in raw.get("campaigns", []) if not campaign.get("sync_error")]
    adsets = [adset for adset in raw.get("adsets", []) if not adset.get("sync_error")]
    ads = [ad for ad in raw.get("ads", []) if not ad.get("sync_error")]
    audited_adsets = [audit_adset(adset) for adset in adsets]
    risks = build_risks(campaigns, audited_adsets)
    placement_counter = Counter(placement for adset in audited_adsets for placement in adset["placements"])
    objective_counter = Counter(normalize_text(campaign.get("objective")) for campaign in campaigns)

    return {
        "summary": {
            "campaigns": len(campaigns),
            "adsets": len(adsets),
            "ads": len(ads),
            "advantageAudienceAdsets": sum(1 for adset in audited_adsets if adset["advantageAudience"]),
            "instagramOnlyAdsets": sum(1 for adset in audited_adsets if adset["platformStrategy"] == "instagram_only"),
            "facebookMixedAdsets": sum(1 for adset in audited_adsets if adset["platformStrategy"] == "mixed_facebook_instagram"),
            "countryTargetedAdsets": sum(1 for adset in audited_adsets if adset["geoStrategy"] == "country"),
            "regionTargetedAdsets": sum(1 for adset in audited_adsets if adset["geoStrategy"] == "region_or_city"),
        },
        "campaigns": [audit_campaign(campaign) for campaign in campaigns],
        "adsets": audited_adsets,
        "placementMix": [{"placement": key, "adsetCount": value} for key, value in placement_counter.most_common()],
        "objectiveMix": [{"objective": key or "unknown", "campaignCount": value} for key, value in objective_counter.most_common()],
        "risks": risks,
        "policy": {
            "executionMode": "read_only_until_approved",
            "primaryInterface": "meta_api",
            "browserFallback": "approved_actions_only",
        },
    }


def audit_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(campaign.get("id") or ""),
        "name": campaign.get("name") or "Untitled campaign",
        "status": campaign.get("effective_status") or campaign.get("status") or "UNKNOWN",
        "objective": normalize_text(campaign.get("objective")),
        "dailyBudgetUsd": cents_to_usd(campaign.get("daily_budget")),
        "lifetimeBudgetUsd": cents_to_usd(campaign.get("lifetime_budget")),
        "startTime": campaign.get("start_time"),
        "stopTime": campaign.get("stop_time"),
    }


def audit_adset(adset: dict[str, Any]) -> dict[str, Any]:
    targeting = adset.get("targeting") or {}
    placements = extract_placements(targeting)
    locations = extract_locations(targeting)
    interests = extract_interest_names(targeting)
    advantage = bool((targeting.get("targeting_automation") or {}).get("advantage_audience"))
    platform_strategy = classify_platform_strategy(placements)
    geo_strategy = classify_geo_strategy(targeting)

    return {
        "id": str(adset.get("id") or ""),
        "campaignId": str(adset.get("campaign_id") or ""),
        "name": adset.get("name") or "Untitled ad set",
        "status": adset.get("effective_status") or adset.get("status") or "UNKNOWN",
        "optimizationGoal": normalize_text(adset.get("optimization_goal")),
        "dailyBudgetUsd": cents_to_usd(adset.get("daily_budget")),
        "ageMin": int(float(targeting.get("age_min") or 18)),
        "ageMax": int(float(targeting.get("age_max") or 65)),
        "genders": normalize_genders(targeting.get("genders")),
        "locations": locations,
        "geoStrategy": geo_strategy,
        "interests": interests or ["Broad / Advantage audience"],
        "advantageAudience": advantage,
        "placements": placements,
        "platformStrategy": platform_strategy,
        "recommendedUse": recommended_use(geo_strategy, platform_strategy, advantage),
    }


def build_risks(campaigns: list[dict[str, Any]], adsets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    facebook_mixed = [adset for adset in adsets if adset["platformStrategy"] == "mixed_facebook_instagram"]
    if facebook_mixed:
        risks.append({
            "severity": "warning",
            "area": "Placement",
            "title": "Facebook is mixed into cold delivery",
            "detail": f"{len(facebook_mixed)} ad sets include Facebook and Instagram together. For Uzbekistan, validate Facebook quality separately before scaling.",
        })

    broad_without_advantage = [
        adset for adset in adsets
        if adset["geoStrategy"] == "country" and not adset["advantageAudience"]
    ]
    if broad_without_advantage:
        risks.append({
            "severity": "info",
            "area": "Audience",
            "title": "Broad country targeting without Advantage+ audience",
            "detail": "This can be a useful control, but compare it against Advantage+ audience and CRM quality before narrowing.",
        })

    no_budget = [campaign for campaign in campaigns if not cents_to_usd(campaign.get("daily_budget")) and not cents_to_usd(campaign.get("lifetime_budget"))]
    if no_budget:
        risks.append({
            "severity": "info",
            "area": "Budget",
            "title": "Some campaigns have no campaign-level budget",
            "detail": f"{len(no_budget)} campaigns may use ad-set budgets or historical zero budgets.",
        })
    return risks


def extract_placements(targeting: dict[str, Any]) -> list[str]:
    publishers = targeting.get("publisher_platforms") or []
    placements: list[str] = []
    for position in targeting.get("instagram_positions") or []:
        placements.append(f"instagram_{normalize_position(position)}")
    for position in targeting.get("facebook_positions") or []:
        placements.append(f"facebook_{normalize_position(position)}")
    for publisher in publishers:
        publisher = normalize_text(publisher)
        if publisher == "instagram" and not any(item.startswith("instagram_") for item in placements):
            placements.extend(["instagram_feed", "instagram_stories", "instagram_reels"])
        if publisher == "facebook" and not any(item.startswith("facebook_") for item in placements):
            placements.extend(["facebook_feed", "facebook_reels"])
    return sorted(set(placements)) or ["automatic_placements"]


def extract_locations(targeting: dict[str, Any]) -> list[str]:
    geo = targeting.get("geo_locations") or {}
    values = []
    values.extend(geo.get("countries") or [])
    values.extend(item.get("name") or item.get("key") for item in geo.get("regions") or [])
    values.extend(item.get("name") or item.get("key") for item in geo.get("cities") or [])
    return [str(value) for value in values if value] or ["Unknown"]


def extract_interest_names(targeting: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("interests", "behaviors"):
        for item in targeting.get(key) or []:
            if item.get("name"):
                names.append(str(item["name"]))
    for spec in targeting.get("flexible_spec") or []:
        for key in ("interests", "behaviors"):
            for item in spec.get(key) or []:
                if item.get("name"):
                    names.append(str(item["name"]))
    return sorted(set(names))


def classify_platform_strategy(placements: list[str]) -> str:
    has_instagram = any(placement.startswith("instagram_") for placement in placements)
    has_facebook = any(placement.startswith("facebook_") for placement in placements)
    if has_instagram and has_facebook:
        return "mixed_facebook_instagram"
    if has_instagram:
        return "instagram_only"
    if has_facebook:
        return "facebook_only"
    return "automatic_or_other"


def classify_geo_strategy(targeting: dict[str, Any]) -> str:
    geo = targeting.get("geo_locations") or {}
    if geo.get("regions") or geo.get("cities"):
        return "region_or_city"
    if geo.get("countries"):
        return "country"
    return "unknown"


def recommended_use(geo_strategy: str, platform_strategy: str, advantage: bool) -> str:
    if geo_strategy == "country" and platform_strategy == "instagram_only":
        return "Good baseline control"
    if platform_strategy == "mixed_facebook_instagram":
        return "Split placement quality before scaling"
    if advantage:
        return "Use as learning-friendly broad test"
    return "Review against playbook guardrails"


def normalize_genders(value: Any) -> list[str]:
    if not value or value == [0]:
        return ["all"]
    lookup = {1: "male", 2: "female"}
    return [lookup.get(item, str(item)) for item in value]


def normalize_position(value: Any) -> str:
    text = normalize_text(value)
    return {
        "stream": "feed",
        "story": "stories",
        "reels": "reels",
        "facebook_reels": "reels",
    }.get(text, text or "unknown")


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def cents_to_usd(value: Any) -> float:
    try:
        return round(float(value or 0) / 100, 2)
    except (TypeError, ValueError):
        return 0

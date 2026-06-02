from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


ACTION_ALIASES = {
    "lead": {"lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"},
    "purchase": {"purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase"},
    "registration": {"complete_registration", "offsite_conversion.fb_pixel_complete_registration"},
    "link_click": {"link_click"},
    "landing_visit": {"landing_page_view", "omni_landing_page_view"},
}


def build_meta_analysis(raw: dict[str, Any], llm_summary: str | None = None) -> dict[str, Any]:
    base_rows = valid_rows(raw.get("insights", {}).get("base", []))
    age_gender_rows = raw.get("insights", {}).get("age_gender", [])
    country_rows = raw.get("insights", {}).get("country", [])
    region_rows = raw.get("insights", {}).get("region", [])
    placement_rows = raw.get("insights", {}).get("placement", [])
    adsets = raw.get("adsets", [])
    ads = raw.get("ads", [])
    sync_errors = collect_sync_errors(raw)

    summary_rows = base_rows or valid_rows(country_rows) or valid_rows(age_gender_rows)

    analysis = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "window": "last_90d",
        "summary": summarize_overall(summary_rows),
        "topCampaigns": rank_dimension(summary_rows, ["campaign_id", "campaign_name"], limit=10),
        "topAds": enrich_ads(rank_dimension(summary_rows, ["ad_id", "ad_name"], limit=15), ads),
        "audience": {
            "ageGender": rank_dimension(age_gender_rows, ["age", "gender"], limit=20),
            "countries": rank_dimension(country_rows, ["country"], limit=20),
            "regions": rank_dimension(region_rows, ["region"], limit=25),
            "interests": analyze_interests(adsets, base_rows),
        },
        "placements": rank_dimension(placement_rows, ["publisher_platform", "platform_position"], limit=25),
        "recommendations": [],
        "lessons": [],
        "rawCounts": {
            "campaigns": len(raw.get("campaigns", [])),
            "adsets": len(adsets),
            "ads": len(ads),
            "baseInsightRows": len(base_rows),
            "ageGenderRows": len(age_gender_rows),
            "countryRows": len(country_rows),
            "regionRows": len(region_rows),
            "placementRows": len(placement_rows),
        },
        "syncErrors": sync_errors,
    }

    analysis["recommendations"] = build_recommendations(analysis)
    analysis["lessons"] = build_lessons(analysis)
    if llm_summary:
        analysis["llmSummary"] = llm_summary

    return {
        "raw": raw,
        "analysis": analysis,
    }


def summarize_overall(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = valid_rows(rows)
    totals = aggregate_rows(rows)
    return {
        **totals,
        "ctr": ratio(totals["clicks"], totals["impressions"]) * 100,
        "cpc": ratio(totals["spend"], totals["clicks"]),
        "cpl": ratio(totals["spend"], totals["leads"]),
        "cpp": ratio(totals["spend"], totals["purchases"]),
        "leadRateFromClick": ratio(totals["leads"], totals["clicks"]) * 100,
        "purchaseRateFromClick": ratio(totals["purchases"], totals["clicks"]) * 100,
    }


def rank_dimension(rows: list[dict[str, Any]], keys: list[str], limit: int = 10) -> list[dict[str, Any]]:
    rows = valid_rows(rows)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        label_parts = [str(row.get(key, "Unknown") or "Unknown") for key in keys]
        label = " / ".join(label_parts)
        current = grouped.setdefault(label, {"label": label, "keys": {key: row.get(key) for key in keys}, "rows": 0})
        merge_metrics(current, row)

    ranked = []
    for item in grouped.values():
        finalize_metrics(item)
        ranked.append(item)

    return sorted(ranked, key=quality_sort, reverse=True)[:limit]


def analyze_interests(adsets: list[dict[str, Any]], base_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adsets = valid_rows(adsets)
    base_rows = valid_rows(base_rows)
    rows_by_adset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in base_rows:
        rows_by_adset[row.get("adset_id", "")].append(row)

    interest_groups: dict[str, dict[str, Any]] = {}
    for adset in adsets:
        adset_rows = rows_by_adset.get(adset.get("id", ""), [])
        interests = extract_interests(adset.get("targeting", {}))
        if not interests:
            interests = ["Broad / no explicit interests"]
        for interest in interests:
            current = interest_groups.setdefault(interest, {"label": interest, "rows": 0, "adsetCount": 0})
            current["adsetCount"] += 1
            for row in adset_rows:
                merge_metrics(current, row)

    ranked = []
    for item in interest_groups.values():
        finalize_metrics(item)
        ranked.append(item)
    return sorted(ranked, key=quality_sort, reverse=True)[:25]


def enrich_ads(items: list[dict[str, Any]], ads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ad_lookup = {ad.get("id"): ad for ad in ads}
    for item in items:
        ad = ad_lookup.get(item["keys"].get("ad_id"), {})
        creative = ad.get("creative", {})
        item["creative"] = {
            "id": creative.get("id"),
            "name": creative.get("name"),
            "title": creative.get("title"),
            "body": creative.get("body"),
            "objectType": creative.get("object_type"),
            "thumbnailUrl": creative.get("thumbnail_url"),
            "videoId": creative.get("video_id"),
        }
    return items


def build_recommendations(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations = []
    min_spend = max(5, analysis["summary"].get("spend", 0) * 0.02)
    age_gender = analysis["audience"]["ageGender"]
    countries = analysis["audience"]["countries"]
    regions = analysis["audience"]["regions"]
    placements = analysis["placements"]
    interests = analysis["audience"]["interests"]

    best_age_gender = first_eligible(age_gender, min_spend)
    if best_age_gender:
        recommendations.append({
            "area": "Audience",
            "title": f"Prioritize {best_age_gender['label']} in the next controlled test",
            "reason": explain_quality(best_age_gender),
        })
    if countries:
        best_country = countries[0]
        recommendations.append({
            "area": "Geo",
            "title": f"Start broad country targeting with a watchlist for {best_country['label']}",
            "reason": "Country-level targeting gives Meta more room to optimize; move to region-level only when a region has enough spend and consistently better cost per quality result.",
        })
    best_region = first_eligible(regions, min_spend)
    if best_region:
        recommendations.append({
            "area": "Geo",
            "title": f"Monitor region performance, especially {best_region['label']}",
            "reason": explain_quality(best_region),
        })
    eligible_placements = [item for item in placements if item.get("spend", 0) >= min_spend]
    if eligible_placements:
        best_placement = eligible_placements[0]
        weak = eligible_placements[-1]
        recommendations.append({
            "area": "Placement",
            "title": f"Scale placement tests around {best_placement['label']} and cap weak delivery on {weak['label']}",
            "reason": "Use buyer/lead quality first, not only CPM or clicks.",
        })
    best_interest = first_eligible(interests, min_spend)
    if best_interest:
        recommendations.append({
            "area": "Interest",
            "title": f"Use {best_interest['label']} as a reference interest cluster",
            "reason": explain_quality(best_interest),
        })

    return recommendations


def build_lessons(analysis: dict[str, Any]) -> list[str]:
    lessons = []
    summary = analysis["summary"]
    if summary["leads"] and not summary["purchases"]:
        lessons.append("Lead events exist but purchase events are missing or not attributed; optimize carefully until purchase tracking is confirmed.")
    if summary["clicks"] and summary["leadRateFromClick"] < 5:
        lessons.append("Click-to-lead rate is weak; audit landing page promise, page load, and CTA match.")
    if analysis["placements"]:
        lessons.append(f"Placement quality is uneven; current best-ranked placement is {analysis['placements'][0]['label']}.")
    if analysis["audience"]["ageGender"]:
        lessons.append(f"Best-ranked age/gender segment is {analysis['audience']['ageGender'][0]['label']}; use this as a starting hypothesis, not a permanent rule.")
    return lessons


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    rows = valid_rows(rows)
    totals = empty_metrics()
    for row in rows:
        merge_metrics(totals, row)
    finalize_metrics(totals)
    return totals


def merge_metrics(target: dict[str, Any], row: dict[str, Any]) -> None:
    target["rows"] = target.get("rows", 0) + 1
    target["spend"] = target.get("spend", 0) + as_float(row.get("spend"))
    target["impressions"] = target.get("impressions", 0) + as_float(row.get("impressions"))
    target["reach"] = target.get("reach", 0) + as_float(row.get("reach"))
    target["clicks"] = target.get("clicks", 0) + as_float(row.get("clicks"))
    # Business definition: "leads" is the website-registration conversion proxy. We sum
    # Meta's `lead` and `complete_registration` actions because this account uses them
    # interchangeably across campaigns (some report one, some the other). NOTE: if a single
    # objective ever reports BOTH for the same conversion this would double-count — revisit
    # with real per-campaign action data before trusting lead volume as buyer quality.
    target["leads"] = target.get("leads", 0) + action_count(row, "lead") + action_count(row, "registration")
    target["purchases"] = target.get("purchases", 0) + action_count(row, "purchase")
    target["linkClicks"] = target.get("linkClicks", 0) + action_count(row, "link_click")


def finalize_metrics(item: dict[str, Any]) -> None:
    item["ctr"] = ratio(item.get("clicks", 0), item.get("impressions", 0)) * 100
    item["cpc"] = ratio(item.get("spend", 0), item.get("clicks", 0))
    item["cpl"] = ratio(item.get("spend", 0), item.get("leads", 0))
    item["cpp"] = ratio(item.get("spend", 0), item.get("purchases", 0))
    item["leadRateFromClick"] = ratio(item.get("leads", 0), item.get("clicks", 0)) * 100
    item["purchaseRateFromClick"] = ratio(item.get("purchases", 0), item.get("clicks", 0)) * 100
    item["qualityScore"] = quality_score(item)


def empty_metrics() -> dict[str, float]:
    return {"rows": 0, "spend": 0, "impressions": 0, "reach": 0, "clicks": 0, "leads": 0, "purchases": 0, "linkClicks": 0}


def quality_score(item: dict[str, Any]) -> float:
    lead_score = min(40, item.get("leadRateFromClick", 0) * 2)
    purchase_score = min(40, item.get("purchaseRateFromClick", 0) * 20)
    ctr_score = min(20, item.get("ctr", 0) * 2)
    return round(lead_score + purchase_score + ctr_score, 2)


def quality_sort(item: dict[str, Any]) -> tuple[float, float, float]:
    return (item.get("qualityScore", 0), item.get("purchases", 0), item.get("leads", 0))


def action_count(row: dict[str, Any], alias: str) -> float:
    action_types = ACTION_ALIASES[alias]
    total = 0.0
    for action in row.get("actions", []) or []:
        if action.get("action_type") in action_types:
            total += as_float(action.get("value"))
    return total


def extract_interests(targeting: dict[str, Any]) -> list[str]:
    interests = []
    for key in ["interests", "flexible_spec"]:
        value = targeting.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("name"):
                    interests.append(item["name"])
                if isinstance(item, dict) and isinstance(item.get("interests"), list):
                    interests.extend(entry.get("name") for entry in item["interests"] if entry.get("name"))
    return sorted(set(interests))


def explain_quality(item: dict[str, Any]) -> str:
    return (
        f"Quality score {item.get('qualityScore', 0)}, spend ${item.get('spend', 0):,.2f}, "
        f"leads {item.get('leads', 0):,.0f}, purchases {item.get('purchases', 0):,.0f}, "
        f"CTR {item.get('ctr', 0):.2f}%, CPL ${item.get('cpl', 0):.2f}."
    )


def ratio(a: float, b: float) -> float:
    return 0 if not b else a / b


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def first_eligible(items: list[dict[str, Any]], min_spend: float) -> dict[str, Any] | None:
    for item in items:
        if item.get("spend", 0) >= min_spend:
            return item
    return None


def valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not row.get("sync_error")]


def collect_sync_errors(raw: dict[str, Any]) -> list[dict[str, str]]:
    errors = []
    for key in ["campaigns", "adsets", "ads", "permissions"]:
        for row in raw.get(key, []):
            if row.get("sync_error"):
                errors.append({"source": key, "error": row["sync_error"]})
    for key, rows in raw.get("insights", {}).items():
        for row in rows:
            if row.get("sync_error"):
                errors.append({"source": f"insights.{key}", "error": row["sync_error"]})
    return errors

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


ACTION_ALIASES = {
    # Meta reports the same lead conversion under several overlapping action types
    # (e.g. `lead`, `onsite_web_lead`, the grouped/pixel variants). They report the
    # SAME number, so `action_count` takes the max within a group rather than summing
    # — summing was inflating lead volume (and CPL/lead-rate) several-fold.
    "lead": {
        "lead",
        "onsite_web_lead",
        "onsite_conversion.lead_grouped",
        "offsite_conversion.fb_pixel_lead",
        "offsite_lead_add_20_s_calls",
    },
    "purchase": {"purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase"},
    "registration": {"complete_registration", "offsite_conversion.fb_pixel_complete_registration"},
    "link_click": {"link_click"},
    "landing_visit": {"landing_page_view", "omni_landing_page_view"},
    # Telegram bot start / subscribe conversion. Like leads, Meta reports the same
    # number under several overlapping pixel + CAPI action types, so action_count
    # takes the max within the group rather than summing.
    "subscribe": {
        "subscribe",
        "onsite_conversion.subscribe_total",
        "offsite_conversion.fb_pixel_subscribe",
        "offsite_conversion.subscribe",
    },
    # Video attention action types (present only for video ads when requested by meta_client).
    "video_thruplay": {"video_thruplay_watched_actions", "thruplay"},
    "video_3s": {"video_view", "video_3_sec_watched_actions"},
    "video_p25": {"video_p25_watched_actions"},
    "video_p50": {"video_p50_watched_actions"},
    "video_p75": {"video_p75_watched_actions"},
    "video_p100": {"video_p100_watched_actions"},
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
        "topCampaigns": attach_campaign_config(
            rank_dimension(summary_rows, ["campaign_id", "campaign_name"], limit=10),
            raw.get("campaigns", []),
            adsets,
        ),
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
        "linkCtr": ratio(totals.get("linkClicks", 0), totals["impressions"]) * 100,
        "cpc": ratio(totals["spend"], totals["clicks"]),
        "cpl": ratio(totals["spend"], totals["leads"]),
        "cpp": ratio(totals["spend"], totals["purchases"]),
        "cpm": ratio(totals["spend"], totals["impressions"]) * 1000,
        "frequency": ratio(totals["impressions"], totals.get("reach", 0)),
        "revenue": totals.get("revenue", 0),
        "roas": ratio(totals.get("revenue", 0), totals["spend"]),
        "aov": ratio(totals.get("revenue", 0), totals["purchases"]),
        "leadRateFromClick": ratio(totals["leads"], totals["clicks"]) * 100,
        "purchaseRateFromClick": ratio(totals["purchases"], totals["clicks"]) * 100,
        **buyer_economics_summary(totals),
    }


def buyer_economics_summary(totals: dict[str, Any]) -> dict[str, Any]:
    leads = totals.get("leads", 0)
    purchases = totals.get("purchases", 0)
    spend = totals.get("spend", 0)
    if purchases > 0:
        return {
            "leadToPurchaseCvr": round(ratio(purchases, leads) * 100, 2) if leads else None,
            "costPerAcquisition": round(ratio(spend, purchases), 2),
            "cacIsProxy": False,
            "cacBasis": "purchase",
        }
    cpl = ratio(spend, leads)
    return {
        "leadToPurchaseCvr": None,
        "costPerAcquisition": round(cpl, 2) if cpl else None,
        "cacIsProxy": True,
        "cacBasis": "cpl_proxy",
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


def attach_campaign_config(
    items: list[dict[str, Any]],
    campaigns: list[dict[str, Any]],
    adsets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach a compact, defensive `config` block to each ranked campaign.

    Captures the real Meta campaign/ad-set settings (objective, buying type, budget
    mode, optimization goal, etc.) so a later workstream can "mirror past winners".
    This is purely additive — it never changes ranking or existing fields, and it
    tolerates missing fields (old/partial/synthetic fixtures) by emitting nulls.
    """
    campaign_lookup = {
        str(campaign.get("id")): campaign
        for campaign in valid_rows(campaigns)
        if campaign.get("id") is not None
    }
    adsets_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for adset in valid_rows(adsets):
        adsets_by_campaign[str(adset.get("campaign_id") or "")].append(adset)

    for item in items:
        campaign_id = str(item.get("keys", {}).get("campaign_id") or "")
        campaign = campaign_lookup.get(campaign_id, {})
        item["config"] = build_campaign_config(campaign, adsets_by_campaign.get(campaign_id, []))
    return items


def build_campaign_config(
    campaign: dict[str, Any],
    campaign_adsets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compact config snapshot for one campaign (+ its ad sets).

    Everything is read with .get and defaults to None when absent, so partial Meta
    payloads or synthetic fixtures never crash the analysis build.
    """
    # Budget mode: a campaign carrying its own budget runs CBO (Campaign Budget
    # Optimization); otherwise budgets live on the ad sets, i.e. ABO. When neither
    # the campaign nor any ad set reports a budget we cannot tell, so leave it null.
    campaign_has_budget = _has_budget(campaign)
    adset_has_budget = any(_has_budget(adset) for adset in campaign_adsets)
    if campaign_has_budget:
        budget_mode = "CBO"
    elif adset_has_budget:
        budget_mode = "ABO"
    else:
        budget_mode = None

    # Ad-set-level config is taken from the first ad set that reports each field so a
    # single representative settings snapshot is surfaced alongside the campaign.
    optimization_goal = _first_adset_value(campaign_adsets, "optimization_goal")
    billing_event = _first_adset_value(campaign_adsets, "billing_event")
    # bid_strategy can live on the campaign (CBO) or the ad set (ABO); prefer the
    # campaign's, then fall back to an ad set's.
    bid_strategy = campaign.get("bid_strategy") or _first_adset_value(campaign_adsets, "bid_strategy")

    return {
        "objective": campaign.get("objective"),
        "buyingType": campaign.get("buying_type"),
        "specialAdCategories": campaign.get("special_ad_categories") or None,
        "budgetMode": budget_mode,
        "optimizationGoal": optimization_goal,
        "billingEvent": billing_event,
        "bidStrategy": bid_strategy,
        "promotedObjectPixelId": _promoted_object_pixel_id(campaign_adsets),
    }


def _has_budget(entity: dict[str, Any]) -> bool:
    return as_float(entity.get("daily_budget")) > 0 or as_float(entity.get("lifetime_budget")) > 0


def _first_adset_value(adsets: list[dict[str, Any]], key: str) -> Any:
    for adset in adsets:
        value = adset.get(key)
        if value not in (None, ""):
            return value
    return None


def _promoted_object_pixel_id(adsets: list[dict[str, Any]]) -> Any:
    for adset in adsets:
        promoted = adset.get("promoted_object")
        if isinstance(promoted, dict):
            pixel_id = promoted.get("pixel_id")
            if pixel_id not in (None, ""):
                return pixel_id
    return None


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
        # When an ad set stacks several interests, Meta does not attribute results to a
        # single interest — each interest below inherits the SAME ad-set metrics, so they
        # are not independently ranked performers. Flag that shared attribution.
        shared = len(interests) > 1
        for interest in interests:
            current = interest_groups.setdefault(
                interest,
                {"label": interest, "rows": 0, "adsetCount": 0, "sharedAttribution": False},
            )
            current["adsetCount"] += 1
            if shared:
                current["sharedAttribution"] = True
            for row in adset_rows:
                merge_metrics(current, row)

    ranked = []
    for item in interest_groups.values():
        finalize_metrics(item)
        # Make the attribution limitation explicit on every interest item. Where the metric
        # was inherited from a multi-interest ad set, we describe it as "present in winning
        # ad sets" rather than an independently ranked performer.
        item["attributionCaveat"] = (
            "Metrics are inherited from the ad set's full interest stack and shared across "
            "all its interests; treat as 'present in winning ad sets', not independently ranked."
            if item.get("sharedAttribution")
            else "Single-interest ad set, so the metric is attributable to this interest."
        )
        item["independentlyRanked"] = not item.get("sharedAttribution", False)
        ranked.append(item)
    return sorted(ranked, key=quality_sort, reverse=True)[:25]


def rank_audiences_for_next_campaign(
    analysis: dict[str, Any],
    exclude_labels: Any = None,
    n: int = 3,
) -> list[dict[str, Any]]:
    """Return up to `n` best audiences to test next, NOT already in `exclude_labels`.

    Reuses the same ranked interest evidence that analyze_interests/rank_dimension/
    quality_score produced upstream (analysis["audience"]["interests"]), so this never
    recomputes ranking math — it only selects, annotates, and de-dupes. The best
    age/gender and region signals are attached as broad targeting hints.

    Preference order: audiences carrying a live Telegram-START signal
    (telegramSubscribers > 0) rank above the rest; within each band the existing
    qualityScore ordering is preserved. Everything is read with .get so partial or
    synthetic knowledge bases never crash.
    """
    audience = (analysis or {}).get("audience", {}) or {}
    interests = audience.get("interests", []) or []

    excluded = {
        _normalize_label(label)
        for label in (exclude_labels or [])
        if _normalize_label(label)
    }

    # Broad supporting signals shared across the suggested audiences. These are the
    # account's best-ranked demographic/geo hints, used only as defaults — never to
    # override anything the interest evidence already implies.
    best_age = _first_label(audience.get("ageGender", []))
    age_range, gender = _split_age_gender(best_age)
    top_regions = [
        item.get("label")
        for item in (audience.get("regions", []) or [])[:3]
        if item.get("label")
    ]
    locations = top_regions or None

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in interests:
        label = item.get("label")
        norm = _normalize_label(label)
        if not norm or norm in excluded or norm in seen:
            continue
        seen.add(norm)
        telegram = _telegram_subscribers(item)
        candidates.append(
            {
                "label": label,
                "ageRange": age_range,
                "gender": gender,
                "locations": locations,
                "interests": [label],
                "qualityScore": item.get("qualityScore", 0),
                "spend": item.get("spend", 0),
                "leads": item.get("leads", 0),
                "telegramSubscribers": telegram,
                "rationale": _audience_rationale(item, telegram),
                "_hasTelegram": telegram is not None and telegram > 0,
            }
        )

    # Stable sort: Telegram-START signal first, then the upstream quality ordering
    # (qualityScore desc) the interests already arrived in.
    ordered = sorted(
        enumerate(candidates),
        key=lambda pair: (
            1 if pair[1]["_hasTelegram"] else 0,
            as_float(pair[1].get("qualityScore")),
            -pair[0],
        ),
        reverse=True,
    )
    result = []
    for _, candidate in ordered[: max(0, int(n or 0))]:
        candidate.pop("_hasTelegram", None)
        result.append(candidate)
    return result


def _telegram_subscribers(item: dict[str, Any]) -> float | None:
    # Rows may carry a live Telegram-START count now; read it defensively from any of
    # the known field spellings. Absent -> None (not 0) so "no data" is distinguishable.
    for key in ("telegramSubscribers", "telegramStarts", "telegram_start"):
        value = item.get(key)
        if value not in (None, ""):
            return as_float(value)
    return None


def _audience_rationale(item: dict[str, Any], telegram: float | None) -> str:
    quality = item.get("qualityScore", 0)
    spend = as_float(item.get("spend"))
    leads = as_float(item.get("leads"))
    if telegram is not None and telegram > 0:
        return (
            f"Live Telegram-START signal ({telegram:,.0f} starts) on '{item.get('label')}' "
            f"with quality score {quality}; untested in recent playbooks, so prioritize it next."
        )
    return (
        f"Quality score {quality} on '{item.get('label')}' (spend ${spend:,.2f}, leads {leads:,.0f}); "
        "untested in recent playbooks, so a strong next-test candidate."
    )


def _normalize_label(label: Any) -> str:
    return str(label or "").strip().lower()


def _split_age_gender(label: Any) -> tuple[str | None, str | None]:
    if not label or "/" not in str(label):
        return None, None
    age_part, _, gender_part = str(label).partition("/")
    age = age_part.strip() or None
    gender = gender_part.strip().lower() or None
    if gender in {"unknown", ""}:
        gender = None
    return age, gender


def _first_label(items: list[dict[str, Any]]) -> str | None:
    for item in items or []:
        if item.get("label"):
            return str(item["label"])
    return None


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
    target["landingPageViews"] = target.get("landingPageViews", 0) + action_count(row, "landing_visit")
    target["subscribes"] = target.get("subscribes", 0) + action_count(row, "subscribe")
    target["revenue"] = target.get("revenue", 0) + action_value(row, "purchase")
    # Video attention inputs. Read defensively — Meta only returns these when a video
    # ad exists and the fields were requested. Summed so hook/hold rates can be computed
    # against impressions/views after aggregation in finalize_metrics.
    target["videoThruplays"] = target.get("videoThruplays", 0) + action_count(row, "video_thruplay")
    target["video3sViews"] = target.get("video3sViews", 0) + video_views_3s(row)
    target["videoP25"] = target.get("videoP25", 0) + action_count(row, "video_p25")
    target["videoP50"] = target.get("videoP50", 0) + action_count(row, "video_p50")
    target["videoP75"] = target.get("videoP75", 0) + action_count(row, "video_p75")
    target["videoP100"] = target.get("videoP100", 0) + action_count(row, "video_p100")


def finalize_metrics(item: dict[str, Any]) -> None:
    item["ctr"] = ratio(item.get("clicks", 0), item.get("impressions", 0)) * 100
    item["linkCtr"] = ratio(item.get("linkClicks", 0), item.get("impressions", 0)) * 100
    item["cpc"] = ratio(item.get("spend", 0), item.get("clicks", 0))
    item["cpl"] = ratio(item.get("spend", 0), item.get("leads", 0))
    item["cpp"] = ratio(item.get("spend", 0), item.get("purchases", 0))
    item["cpm"] = ratio(item.get("spend", 0), item.get("impressions", 0)) * 1000
    item["frequency"] = ratio(item.get("impressions", 0), item.get("reach", 0))
    item["revenue"] = item.get("revenue", 0)
    item["roas"] = ratio(item.get("revenue", 0), item.get("spend", 0))
    item["aov"] = ratio(item.get("revenue", 0), item.get("purchases", 0))
    item["leadRateFromClick"] = ratio(item.get("leads", 0), item.get("clicks", 0)) * 100
    item["purchaseRateFromClick"] = ratio(item.get("purchases", 0), item.get("clicks", 0)) * 100
    # Funnel rates surfaced on the dashboard. Capped at 100% so Meta's cross-window
    # attribution overshoot (e.g. landing views > link clicks) can't render an
    # impossible >100% rate. Visit rate measures against link clicks, falling back
    # to all clicks only when link clicks are absent.
    visit_base = item.get("linkClicks", 0) or item.get("clicks", 0)
    item["visitRate"] = min(100.0, ratio(item.get("landingPageViews", 0), visit_base) * 100)
    item["leadRate"] = min(100.0, ratio(item.get("leads", 0), item.get("landingPageViews", 0)) * 100)
    item["startRate"] = min(100.0, ratio(item.get("subscribes", 0), item.get("leads", 0)) * 100)
    finalize_buyer_economics(item)
    # A lead rate above 100% is a structural double-count signal, not a great segment.
    item["leadDoubleCountRisk"] = item["leadRateFromClick"] > 100
    finalize_video_attention(item)
    item["qualityScore"] = quality_score(item)


def finalize_buyer_economics(item: dict[str, Any]) -> None:
    """Lead->purchase conversion and customer acquisition cost.

    When real purchase data exists we report a true CVR and CAC (cost-per-acquisition =
    spend/purchases). When it does not, we fall back to CPL as a CAC PROXY and label it
    explicitly (cacIsProxy=True) so downstream consumers never treat a registration cost
    as a real customer cost.
    """
    leads = item.get("leads", 0)
    purchases = item.get("purchases", 0)
    spend = item.get("spend", 0)
    cpl = item.get("cpl", ratio(spend, leads))
    if purchases > 0:
        item["leadToPurchaseCvr"] = round(ratio(purchases, leads) * 100, 2) if leads else None
        item["costPerAcquisition"] = round(ratio(spend, purchases), 2)
        item["cacIsProxy"] = False
        item["cacBasis"] = "purchase"
    else:
        item["leadToPurchaseCvr"] = None  # no purchase signal yet
        item["costPerAcquisition"] = round(cpl, 2) if cpl else None
        item["cacIsProxy"] = True
        item["cacBasis"] = "cpl_proxy"


def finalize_video_attention(item: dict[str, Any]) -> None:
    """Hook rate (3s views / impressions) and hold rate (avg % watched).

    Only populated when video inputs exist; otherwise the fields stay None so
    downstream consumers can degrade gracefully and not confuse 0 with "no data".
    """
    impressions = item.get("impressions", 0)
    three_s = item.get("video3sViews", 0)
    thruplays = item.get("videoThruplays", 0)
    p25 = item.get("videoP25", 0)
    p50 = item.get("videoP50", 0)
    p75 = item.get("videoP75", 0)
    p100 = item.get("videoP100", 0)
    has_video = any([three_s, thruplays, p25, p50, p75, p100])

    item["hookRate"] = round(ratio(three_s, impressions) * 100, 2) if (has_video and impressions) else None
    item["thruplayRate"] = round(ratio(thruplays, impressions) * 100, 2) if (has_video and impressions) else None
    # Hold rate: average fraction of the video watched, approximated from the quartile
    # completion curve relative to 3s/thruplay starts. Uses midpoints of each quartile band.
    starts = three_s or thruplays or impressions
    if has_video and starts:
        # Quartile completion counts weighted by their band midpoints (0-25% -> 12.5%,
        # 25-50% -> 37.5%, ...). The weighted average approximates avg % watched / hold rate.
        weighted = p25 * 12.5 + p50 * 37.5 + p75 * 62.5 + p100 * 93.75
        denominator = p25 + p50 + p75 + p100
        item["holdRate"] = round(weighted / denominator, 2) if denominator else None
    else:
        item["holdRate"] = None


def empty_metrics() -> dict[str, float]:
    return {
        "rows": 0,
        "spend": 0,
        "impressions": 0,
        "reach": 0,
        "clicks": 0,
        "leads": 0,
        "purchases": 0,
        "linkClicks": 0,
        "landingPageViews": 0,
        "subscribes": 0,
        "revenue": 0,
    }


def quality_score(item: dict[str, Any]) -> float:
    """Composite 0-100 ranking score.

    Rebalanced from the old formula (which gave 40 dead points to an always-zero
    purchase term, capped CTR at an unreachable 10%, and let a >100% lead rate
    saturate the score). Now: delivery quality is worth up to 70 (lead rate +
    realistic link-CTR scale + a volume/confidence term so thin segments don't tie
    with high-volume ones), and proven buyer activity (purchases / ROAS) is a bonus
    of up to 30 ON TOP — not a precondition for a high score, but the only way past 70.
    """
    lead_rate = min(100.0, item.get("leadRateFromClick", 0))  # clamp double-count inflation
    ctr = item.get("ctr", 0)
    clicks = item.get("clicks", 0)

    lead_component = min(40.0, lead_rate * 0.8)                # ~50% lead rate -> 40
    ctr_component = min(15.0, ctr * 6.0)                       # ~2.5% link CTR -> 15
    volume_component = min(15.0, math.log10(max(1.0, clicks)) * 5.0)  # 1k clicks -> 15
    score = lead_component + ctr_component + volume_component

    if item.get("purchases", 0) > 0:
        purchase_rate = min(100.0, item.get("purchaseRateFromClick", 0))
        score += min(20.0, purchase_rate * 10.0)              # ~2% purchase rate -> 20
        roas = item.get("roas", 0)
        if roas:
            score += min(10.0, roas * 2.5)                    # ~4x ROAS -> 10

    return round(min(100.0, score), 2)


def quality_sort(item: dict[str, Any]) -> tuple[float, float, float]:
    return (item.get("qualityScore", 0), item.get("purchases", 0), item.get("leads", 0))


def action_count(row: dict[str, Any], alias: str) -> float:
    # Take the MAX across the alias group (not the sum): Meta repeats the same
    # conversion under multiple overlapping action types, so summing double-counts.
    # Video attention metrics are returned by Meta as their own top-level list fields
    # (e.g. video_p25_watched_actions), so we also scan any same-named top-level field.
    action_types = ACTION_ALIASES[alias]
    values = [
        as_float(action.get("value"))
        for action in row.get("actions", []) or []
        if action.get("action_type") in action_types
    ]
    for field in action_types:
        field_value = row.get(field)
        if isinstance(field_value, list):
            values.extend(as_float(entry.get("value")) for entry in field_value if isinstance(entry, dict))
        elif field_value not in (None, ""):
            values.append(as_float(field_value))
    return max(values, default=0.0)


def video_views_3s(row: dict[str, Any]) -> float:
    return action_count(row, "video_3s")


def action_value(row: dict[str, Any], alias: str = "purchase") -> float:
    # Revenue lives in `action_values` (a list parallel to `actions`). Same max-over-group
    # dedup logic as action_count. Used to compute ROAS/AOV from purchase revenue.
    action_types = ACTION_ALIASES[alias]
    values = [
        as_float(action.get("value"))
        for action in row.get("action_values", []) or []
        if action.get("action_type") in action_types
    ]
    return max(values, default=0.0)


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

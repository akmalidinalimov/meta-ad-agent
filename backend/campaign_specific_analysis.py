from __future__ import annotations

from collections import defaultdict
from typing import Any

from .analysis_engine import action_count, as_float


_ROSTER_TRIGGERS = (
    "active campaign", "running campaign", "live campaign", "paused campaign", "what campaign",
    "which campaign", "list campaign", "list my campaign", "how many campaign", "campaigns are",
    "campaign status", "active campaigns", "running campaigns", "show campaign", "my campaigns",
)


_SNAPSHOT_FOOTER = "\n\n_As of last sync; live Meta data was unavailable._"


def _with_footer(answer: str | None, source: str) -> str | None:
    """Append the stale-data footer when answering from the snapshot fallback."""
    if answer is None:
        return None
    if source == "snapshot":
        return answer + _SNAPSHOT_FOOTER
    return answer


def campaign_roster_answer(
    question: str,
    knowledge: dict[str, Any],
    *,
    campaigns: list[dict[str, Any]] | None = None,
    source: str = "snapshot",
) -> str | None:
    """Deterministic, always-grounded answer for 'what campaigns are active/paused?' style
    questions: lists the real campaigns and their status.

    When ``campaigns`` is provided it is used as the campaign list (e.g. live Meta data);
    otherwise the saved knowledge base is read, preserving today's behavior exactly.
    A ``source == "snapshot"`` answer is annotated with a stale-data footer.
    Returns None when the question isn't about the campaign roster."""
    lower = question.lower()
    if not any(trigger in lower for trigger in _ROSTER_TRIGGERS):
        return None
    source_campaigns = campaigns if campaigns is not None else knowledge.get("raw", {}).get("campaigns", [])
    campaigns = [
        c for c in (source_campaigns or [])
        if isinstance(c, dict) and c.get("name")
    ]
    if not campaigns:
        return None

    def status_of(campaign: dict[str, Any]) -> str:
        return str(campaign.get("status") or campaign.get("effective_status") or "UNKNOWN").upper()

    active = [c for c in campaigns if status_of(c) == "ACTIVE"]
    paused = [c for c in campaigns if status_of(c) == "PAUSED"]
    want_active = "active" in lower or "running" in lower or "live" in lower
    want_paused = "paused" in lower
    if want_active and not want_paused:
        selected, label = active, "Active"
    elif want_paused and not want_active:
        selected, label = paused, "Paused"
    else:
        selected, label = campaigns, "All"

    lines = [f"You have **{len(campaigns)}** campaigns: **{len(active)}** active, **{len(paused)}** paused."]
    if not selected:
        lines.append(f"\nNo {label.lower()} campaigns right now.")
        return _with_footer("\n".join(lines), source)
    lines.append("")
    lines.append(f"{label} campaigns:")
    for campaign in selected[:25]:
        budget = campaign.get("daily_budget")
        try:
            budget_str = f" — ${float(budget) / 100:,.0f}/day" if budget else ""
        except (TypeError, ValueError):
            budget_str = ""
        objective = campaign.get("objective")
        meta = status_of(campaign) + (f", {objective}" if objective else "")
        lines.append(f"- {campaign['name']} ({meta}){budget_str}")
    if len(selected) > 25:
        lines.append(f"- …and {len(selected) - 25} more")
    return _with_footer("\n".join(lines), source)


def campaign_specific_answer(
    question: str,
    knowledge: dict[str, Any],
    *,
    campaigns: list[dict[str, Any]] | None = None,
    source: str = "snapshot",
) -> str | None:
    campaign = find_campaign(question, knowledge, campaigns=campaigns, source=source)
    if not campaign:
        return None

    rows = campaign_insight_rows(campaign, knowledge)
    if not rows:
        return _with_footer(
            (
                f"I found campaign {campaign['name']}, but the saved knowledge base has no matching insight rows for it. "
                "Refresh Meta data, then ask again for campaign-specific rankings."
            ),
            source,
        )

    lower = question.lower()
    if any(word in lower for word in ["creative", "video", "ad ", "ads ", "hook", "thumbnail", "viral"]):
        return _with_footer(creative_answer(campaign, rows, knowledge), source)
    if any(word in lower for word in ["placement", "facebook", "instagram", "reels", "stories", "feed", "threads"]):
        return _with_footer(placement_answer(campaign, rows), source)
    return _with_footer(audience_answer(campaign, rows), source)


def find_campaign(
    question: str,
    knowledge: dict[str, Any],
    *,
    campaigns: list[dict[str, Any]] | None = None,
    source: str = "snapshot",
) -> dict[str, Any] | None:
    raw = knowledge.get("raw", {})
    question_key = normalize(question)
    campaigns = campaigns if campaigns is not None else (raw.get("campaigns", []) or [])
    exact_matches = [
        campaign
        for campaign in campaigns
        if campaign.get("id") and str(campaign["id"]) in question
        or campaign.get("name") and normalize(campaign["name"]) in question_key
    ]
    if exact_matches:
        return normalize_campaign(exact_matches[0])

    named_matches = [
        campaign
        for campaign in campaigns
        if campaign.get("name") and all(part in question_key for part in important_name_parts(campaign["name"]))
    ]
    return normalize_campaign(named_matches[0]) if named_matches else None


def normalize_campaign(campaign: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(campaign.get("id") or ""),
        "name": str(campaign.get("name") or campaign.get("campaign_name") or "Unknown campaign"),
    }


def important_name_parts(name: str) -> list[str]:
    parts = [part for part in normalize(name).split() if len(part) >= 3]
    return parts[:6]


def campaign_insight_rows(campaign: dict[str, str], knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows = knowledge.get("raw", {}).get("insights", {}).get("base", []) or []
    campaign_id = campaign.get("id")
    campaign_name = normalize(campaign.get("name", ""))
    return [
        row
        for row in rows
        if (campaign_id and str(row.get("campaign_id") or "") == campaign_id)
        or (campaign_name and normalize(str(row.get("campaign_name") or "")) == campaign_name)
    ]


def audience_answer(campaign: dict[str, str], rows: list[dict[str, Any]]) -> str:
    ranked = rank_rows(rows, ["adset_id", "adset_name"])
    top_lines = format_ranked(ranked[:5])
    best = ranked[0] if ranked else None
    recommendation = ""
    if best:
        diagnosis = audience_diagnosis(best)
        recommendation = (
            f"\n\nRecommendation: use {best['label']} as the first scale candidate because it has the strongest cost-per-lead "
            f"inside this campaign. {diagnosis} Treat this as website-registration quality only until Telegram START and CRM purchase data are connected."
        )
    return (
        f"Campaign-specific audience ranking for {campaign['name']}:\n"
        f"{top_lines}"
        f"{recommendation}"
    )


def creative_answer(campaign: dict[str, str], rows: list[dict[str, Any]], knowledge: dict[str, Any]) -> str:
    ranked = rank_rows(rows, ["ad_id", "ad_name"])
    ads = knowledge.get("raw", {}).get("ads", []) or []
    ad_lookup = {str(ad.get("id")): ad for ad in ads}
    enriched = []
    for item in ranked[:10]:
        ad = ad_lookup.get(item.get("id", ""))
        creative = ad.get("creative", {}) if ad else {}
        enriched.append({
            **item,
            "hasThumbnail": bool(creative.get("thumbnail_url")),
            "videoId": creative.get("video_id"),
        })

    lines = []
    for index, item in enumerate(enriched, start=1):
        media = "thumbnail+video" if item.get("hasThumbnail") and item.get("videoId") else "metadata only"
        lines.append(f"{index}. {item['label']}: {metric_sentence(item)}; {media}. {creative_diagnosis(item)}")

    return (
        f"Campaign-specific creative ranking for {campaign['name']}:\n"
        + "\n".join(lines or ["No creative rows were found."])
        + "\n\nRecommendation: replicate the top lead-volume creatives only after checking Telegram START and CRM quality. "
        "A viral creative should be reworked if it attracts low purchasing-power viewers or creates registrations without purchases."
    )


def placement_answer(campaign: dict[str, str], rows: list[dict[str, Any]]) -> str:
    ranked = rank_rows(rows, ["publisher_platform", "platform_position", "placement"])
    if not any(item["label"] != "Unknown" for item in ranked):
        return (
            f"The saved base rows for {campaign['name']} do not include placement breakdowns. "
            "Use the account-level placement tab for now, and refresh Meta with placement breakdowns to rank this campaign precisely."
        )
    return (
        f"Campaign-specific placement ranking for {campaign['name']}:\n"
        + format_ranked(ranked[:8])
        + "\n\nRecommendation: keep Instagram placements separated from Facebook tests so cheap traffic does not hide weak downstream quality."
    )


def rank_rows(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"spend": 0.0, "clicks": 0.0, "leads": 0.0, "purchases": 0.0, "rows": 0}
    )
    for row in rows:
        label = label_for(row, keys)
        item = grouped[label]
        item["id"] = str(row.get(keys[0]) or "")
        item["label"] = label
        item["spend"] += as_float(row.get("spend"))
        item["clicks"] += as_float(row.get("clicks"))
        item["leads"] += action_count(row, "lead") + action_count(row, "registration")
        item["purchases"] += action_count(row, "purchase")
        item["rows"] += 1
    ranked = [with_rates(item) for item in grouped.values()]
    return sorted(ranked, key=rank_key)


def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Quality + volume aware ranking (aligned with analysis_engine), not pure CPL.

    Ranking only by CPL lets a marginally-cheaper low-volume ad set outrank a proven
    high-volume winner. Order: enough-sample first, then higher lead-quality, then
    purchase proof, then lead volume, then cheaper CPL as a final tiebreak.
    """
    cpl = item.get("cpl", 0)
    lead_rate = item.get("leadRateFromClick", 0)
    quality = min(40.0, lead_rate * 2)  # lead-quality proxy, same shape as analysis_engine
    confident = item.get("clicks", 0) >= 50
    return (
        0 if confident else 1,
        -quality,
        -item.get("purchases", 0),
        -item.get("leads", 0),
        cpl if cpl else 1_000_000,
    )


def label_for(row: dict[str, Any], keys: list[str]) -> str:
    if keys == ["adset_id", "adset_name"]:
        return str(row.get("adset_name") or row.get("adset_id") or "Unknown")
    if keys == ["ad_id", "ad_name"]:
        return str(row.get("ad_name") or row.get("ad_id") or "Unknown")
    parts = [str(row.get(key) or "") for key in keys if row.get(key)]
    return " / ".join(parts) if parts else "Unknown"


def with_rates(item: dict[str, Any]) -> dict[str, Any]:
    clicks = item["clicks"]
    leads = item["leads"]
    spend = item["spend"]
    return {
        **item,
        "cpc": spend / clicks if clicks else 0,
        "cpl": spend / leads if leads else 0,
        "leadRateFromClick": (leads / clicks * 100) if clicks else 0,
    }


def format_ranked(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{index}. {item['label']}: {metric_sentence(item)}." for index, item in enumerate(items, start=1))


def metric_sentence(item: dict[str, Any]) -> str:
    return (
        f"${item['spend']:,.2f} spend, {item['clicks']:,.0f} clicks, {item['leads']:,.0f} leads, "
        f"{item.get('purchases', 0):,.0f} purchases, "
        f"CPC ${item['cpc']:.4f}, CPL ${item['cpl']:.2f}, lead rate {item['leadRateFromClick']:.1f}%"
    )


def creative_diagnosis(item: dict[str, Any]) -> str:
    if item.get("leads", 0) >= 100 and item.get("purchases", 0) == 0:
        return "Traffic magnet: audit buyer quality before scaling."
    if item.get("purchases", 0) > 0:
        return "Scale candidate: has downstream purchase proof."
    if item.get("clicks", 0) < 50:
        return "Insufficient data: keep in controlled rotation before judging."
    return "Review candidate: compare lead quality against Telegram/CRM outcomes."


def audience_diagnosis(item: dict[str, Any]) -> str:
    label = str(item.get("label", "")).lower()
    if item.get("purchases", 0) > 0:
        return "It has purchase proof, so it can become a cautious scale candidate."
    if any(word in label for word in ["business", "marketing", "smm", "ai", "job", "work"]):
        return "It matches higher purchasing-power hypotheses, but still needs Telegram/CRM validation."
    if item.get("leads", 0) >= 100:
        return "It is a lead-volume winner, but purchasing power is not proven."
    return "It needs more controlled spend before a strong audience decision."


def normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())

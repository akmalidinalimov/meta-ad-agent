"""Campaign-specific analysis.

Resolves a campaign named in a chat question to its ID, then ranks that
campaign's ad sets, creatives, and placements from the saved Meta insight rows
using real metrics (spend, clicks, leads, CPL, CPC, lead rate). Reuses the
shared aggregation/ranking helpers in analysis_engine so the numbers match the
account-level analysis.
"""

from __future__ import annotations

import re
from typing import Any

from .analysis_engine import enrich_ads, rank_dimension, summarize_overall, valid_rows

# Tokens that are too generic to identify a campaign on their own.
_GENERIC_TOKENS = {
    "the", "and", "for", "from", "with", "campaign", "ad", "ads", "adset", "adsets",
    "creative", "creatives", "audience", "placement", "placements", "should", "which",
    "what", "best", "scale", "worked", "why", "test", "vsl", "new", "this", "that",
}
_LOW_SAMPLE_MIN_CLICKS = 100
_LOW_SAMPLE_MIN_SPEND = 5.0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> set[str]:
    # Split on separators, then strip edge punctuation so "26.04.2026?" -> "26.04.2026".
    raw = re.split(r"[\s\-_/]+", _norm(text))
    return {token.strip(".,!?;:()[]\"'") for token in raw if token.strip(".,!?;:()[]\"'")}


def _distinctive_tokens(name: str) -> set[str]:
    return {token for token in _tokenize(name) if len(token) >= 2 and token not in _GENERIC_TOKENS}


def _campaign_catalog(knowledge: dict[str, Any]) -> list[dict[str, str]]:
    """All known (id, name) pairs from raw campaigns and analysis rankings."""
    catalog: dict[str, str] = {}
    for campaign in (knowledge.get("raw", {}) or {}).get("campaigns", []) or []:
        if campaign.get("sync_error"):
            continue
        cid = str(campaign.get("id") or "")
        name = campaign.get("name") or ""
        if cid and name:
            catalog[cid] = name
    for item in (knowledge.get("analysis", {}) or {}).get("topCampaigns", []) or []:
        keys = item.get("keys", {})
        cid = str(keys.get("campaign_id") or "")
        name = keys.get("campaign_name") or item.get("label") or ""
        if cid and name and cid not in catalog:
            catalog[cid] = name
    return [{"id": cid, "name": name} for cid, name in catalog.items()]


def resolve_campaign(knowledge: dict[str, Any] | None, query: str) -> dict[str, str] | None:
    """Best-effort match of a campaign named in the query. Returns {id, name} or None."""
    if not knowledge:
        return None
    catalog = _campaign_catalog(knowledge)
    if not catalog:
        return None

    normalized_query = _norm(query)
    query_tokens = _tokenize(query)

    best: tuple[float, dict[str, str]] | None = None
    for campaign in catalog:
        name = campaign["name"]
        normalized_name = _norm(name)
        if normalized_name and normalized_name in normalized_query:
            return campaign  # full-name mention wins outright

        distinctive = _distinctive_tokens(name)
        if not distinctive:
            continue
        matched = distinctive & query_tokens
        # Require at least two distinctive tokens (or one that is itself specific,
        # like a numeric/date token) so a stray shared word never resolves.
        specific_hit = any(any(ch.isdigit() for ch in token) for token in matched)
        if len(matched) >= 2 or (specific_hit and len(matched) >= 1):
            score = len(matched) / len(distinctive)
            if best is None or score > best[0]:
                best = (score, campaign)

    return best[1] if best else None


def _campaign_base_rows(knowledge: dict[str, Any], campaign_id: str) -> list[dict[str, Any]]:
    insights = (knowledge.get("raw", {}) or {}).get("insights", {}) or {}
    rows = valid_rows(insights.get("base", []) or [])
    return [row for row in rows if str(row.get("campaign_id") or "") == str(campaign_id)]


def _placement_rows(knowledge: dict[str, Any], campaign_id: str) -> list[dict[str, Any]]:
    insights = (knowledge.get("raw", {}) or {}).get("insights", {}) or {}
    rows = valid_rows(insights.get("placement", []) or [])
    return [row for row in rows if str(row.get("campaign_id") or "") == str(campaign_id)]


def _flag_low_sample(items: list[dict[str, Any]]) -> None:
    for item in items:
        item["lowSample"] = item.get("clicks", 0) < _LOW_SAMPLE_MIN_CLICKS or item.get("spend", 0) < _LOW_SAMPLE_MIN_SPEND


def analyze_campaign(knowledge: dict[str, Any], campaign: dict[str, str]) -> dict[str, Any]:
    campaign_id = campaign["id"]
    base_rows = _campaign_base_rows(knowledge, campaign_id)
    placement_rows = _placement_rows(knowledge, campaign_id) or base_rows
    ads = (knowledge.get("raw", {}) or {}).get("ads", []) or []

    summary = summarize_overall(base_rows)
    adsets = rank_dimension(base_rows, ["adset_id", "adset_name"], limit=10)
    creatives = enrich_ads(rank_dimension(base_rows, ["ad_id", "ad_name"], limit=10), ads)
    placements = rank_dimension(placement_rows, ["publisher_platform", "platform_position"], limit=10)
    for group in (adsets, creatives, placements):
        _flag_low_sample(group)

    return {
        "campaign": campaign,
        "hasData": bool(base_rows),
        "summary": summary,
        "adSets": adsets,
        "creatives": creatives,
        "placements": placements,
        "limitations": _limitations(summary, base_rows, adsets),
    }


def _limitations(summary: dict[str, Any], base_rows: list[dict[str, Any]], adsets: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    if not base_rows:
        notes.append("No per-campaign insight rows are saved yet; run a Meta sync before trusting these numbers.")
        return notes
    if not summary.get("purchases"):
        notes.append("No attributed purchases in the saved data, so ranking is lead/click-quality, not proven buyer quality.")
    if summary.get("leadRateFromClick", 0) and summary["leadRateFromClick"] < 5:
        notes.append("Click-to-lead rate is below 5%; audit the landing page and CTA before scaling.")
    low = [item for item in adsets if item.get("lowSample")]
    if low:
        notes.append(f"{len(low)} ad set(s) have low sample (<{_LOW_SAMPLE_MIN_CLICKS} clicks); treat their ranking as provisional.")
    return notes


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _rank_lines(items: list[dict[str, Any]], limit: int = 5) -> list[str]:
    lines = []
    for item in items[:limit]:
        flag = " [low sample]" if item.get("lowSample") else ""
        lines.append(
            f"- {item['label']}: spend {_money(item.get('spend', 0))}, "
            f"clicks {item.get('clicks', 0):,.0f}, leads {item.get('leads', 0):,.0f}, "
            f"CPL {_money(item.get('cpl', 0))}, CPC {_money(item.get('cpc', 0))}, "
            f"lead rate {item.get('leadRateFromClick', 0):.1f}%{flag}"
        )
    return lines


def format_campaign_analysis(result: dict[str, Any], focus: str) -> str:
    campaign = result["campaign"]
    summary = result["summary"]
    header = [
        f"Campaign: {campaign['name']} (ID {campaign['id']}).",
    ]
    if not result["hasData"]:
        header.append("I could not find saved per-campaign insight rows for it yet. Run a Meta sync, then ask again.")
        return "\n".join(header)

    header.append(
        f"Totals: spend {_money(summary.get('spend', 0))}, clicks {summary.get('clicks', 0):,.0f}, "
        f"leads {summary.get('leads', 0):,.0f}, CPL {_money(summary.get('cpl', 0))}, "
        f"CPC {_money(summary.get('cpc', 0))}, lead rate {summary.get('leadRateFromClick', 0):.1f}%."
    )

    sections: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("adSets", "Ad sets ranked by quality (then leads)", result["adSets"]),
        ("creatives", "Creatives ranked by quality (then leads)", result["creatives"]),
        ("placements", "Placements ranked by quality", result["placements"]),
    ]
    focus_key = {"audience": "adSets", "creative": "creatives", "placement": "placements"}.get(focus)
    if focus_key:
        sections.sort(key=lambda section: 0 if section[0] == focus_key else 1)

    body: list[str] = []
    for _, title, items in sections:
        body.append("")
        body.append(f"{title}:")
        body.extend(_rank_lines(items) or ["- No rows found for this dimension."])

    limitations = result["limitations"]
    if limitations:
        body.append("")
        body.append("Limitations:")
        body.extend(f"- {note}" for note in limitations)

    body.append("")
    body.append("These are real per-campaign Meta metrics. I will not change anything without approval.")
    return "\n".join(header + body)


def campaign_analysis_from_question(knowledge: dict[str, Any] | None, question: str, focus: str = "audit") -> dict[str, Any] | None:
    """Return campaign-specific analysis if the question names a known campaign, else None."""
    campaign = resolve_campaign(knowledge, question)
    if not campaign:
        return None
    result = analyze_campaign(knowledge, campaign)
    return {
        "campaign": campaign,
        "result": result,
        "answer": format_campaign_analysis(result, focus),
    }

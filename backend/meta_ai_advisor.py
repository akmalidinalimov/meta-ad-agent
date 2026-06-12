"""Meta AI Advisor + Strategist analysis of a captured Ads Manager AI panel.

Deterministic, evidence-based heuristics (no LLM dependency) so the workflow is
testable. The Advisor summarizes what Meta AI said and how far to trust it; the
Strategist scores it against the 180-day knowledge base, campaign-specific
metrics, and the Uzbekistan course business context.
"""

from __future__ import annotations

import re
from typing import Any

from .campaign_analysis import analyze_campaign, resolve_campaign

# Delivery/auction terms Meta AI typically cites as evidence.
ADVISOR_EVIDENCE_TERMS = [
    "ctr", "cpm", "cpc", "cpl", "cost per", "reach", "frequency", "impressions",
    "opportunity score", "learning", "conversions", "results", "advantage+",
    "advantage", "audience", "placement", "budget", "roas", "delivery",
]

# Risk / caveat language that signals the recommendation is hedged.
RISK_TERMS = [
    "risk", "caveat", "overlap", "learning phase", "fatigue", "saturation",
    "limited", "may ", "could ", "monitor", "gradually", "test", "volatile",
]

# Imperative verbs that make a line an actual recommendation.
ACTION_VERBS = [
    "increase", "raise", "scale", "expand", "broaden", "add", "test", "reduce",
    "lower", "decrease", "pause", "turn off", "turn on", "enable", "disable",
    "duplicate", "consolidate", "allocate", "shift", "move", "optimize", "try",
    "consider", "recommend", "use ", "set ", "target", "combine",
]

# Business-side signals the operator cares about. Missing -> Meta AI blind spot.
# (label, trigger terms, is_critical_for_realism)
BUSINESS_SIGNAL_GROUPS: list[tuple[str, set[str], bool]] = [
    ("Telegram START quality", {"telegram", "start", "bot"}, True),
    ("CRM / sales-stage progression", {"crm", "bitrix", "pipeline", "stage"}, False),
    ("Paid course purchases / buyer quality", {"purchase", "buyer", "paid", "revenue", "roas"}, True),
    ("Audience purchasing power", {"purchasing power", "income", "affluent", "high-value"}, True),
    ("Sales team capacity (1-hour contact)", {"sales team", "capacity", "lead volume", "follow up", "follow-up"}, True),
    ("Uzbekistan market context", {"uzbek", "tashkent", "uzs", "uzbekistan"}, False),
]


def _numbers(text: str) -> list[str]:
    return re.findall(r"\$\s?\d[\d,.]*|\b\d[\d,.]*\s?%|\b\d[\d,.]*\b", text)


def _percent_values(text: str) -> list[float]:
    values = []
    for match in re.findall(r"(\d[\d,.]*)\s?%", text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return values


def _money_values(text: str) -> list[float]:
    values = []
    for match in re.findall(r"\$\s?(\d[\d,.]*)", text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return values


def extract_recommendations(text: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in re.split(r"[\n\r]+", text):
        for sentence in re.split(r"(?<=[.!])\s+", raw_line):
            cleaned = sentence.strip().lstrip("-•*0123456789. )").strip()
            if len(cleaned) < 8:
                continue
            lower = cleaned.lower()
            if any(verb in lower for verb in ACTION_VERBS) or "opportunity" in lower:
                candidates.append(cleaned)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for item in candidates:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:8]


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def comparison_scores(
    text: str,
    recommendations: list[str],
    evidence: list[str],
    numbers: list[str],
    missed_critical: int,
    *,
    knowledge: dict[str, Any] | None,
    campaign_metrics: dict[str, Any] | None,
) -> dict[str, int]:
    lower = text.lower()

    specificity = _clamp(
        20
        + min(60, len(numbers) * 12)
        + (20 if campaign_metrics else 0)
        + (10 if "%" in text else 0)
    )

    if not knowledge:
        metric_accuracy = 40  # nothing to verify against
    elif campaign_metrics and campaign_metrics.get("hasData") and _money_values(text):
        real_cpl = campaign_metrics["summary"].get("cpl", 0)
        cited = _money_values(text)
        close = real_cpl > 0 and any(abs(value - real_cpl) <= max(0.5, real_cpl * 0.5) for value in cited)
        metric_accuracy = 88 if close else 58
    elif numbers:
        metric_accuracy = 62
    else:
        metric_accuracy = 45

    actionability = _clamp(15 + len(recommendations) * 22)

    business_realism = _clamp(100 - missed_critical * 22)

    risk_hits = sum(1 for term in RISK_TERMS if term in lower)
    risk_awareness = _clamp(15 + risk_hits * 28) if risk_hits else 15

    return {
        "specificity": specificity,
        "metricAccuracy": metric_accuracy,
        "actionability": actionability,
        "businessRealism": business_realism,
        "riskAwareness": risk_awareness,
    }


def trust_level(scores: dict[str, int], evidence: list[str], recommendations: list[str]) -> str:
    overall = sum(scores.values()) / len(scores)
    if overall >= 68 and evidence and recommendations:
        return "high"
    if overall >= 45 and recommendations:
        return "medium"
    return "low"


def _business_counterpoints(missed: list[str], knowledge: dict[str, Any] | None, campaign_metrics: dict[str, Any] | None) -> list[str]:
    points: list[str] = []
    if "Telegram START quality" in missed:
        points.append("Meta AI optimizes for on-platform results; verify Telegram START quality before trusting cheaper leads.")
    if "Paid course purchases / buyer quality" in missed:
        points.append("No buyer/purchase signal in the capture. Treat its 'results' as lead-quality, not proven buyers.")
    if "Audience purchasing power" in missed:
        points.append("Cheap audiences (students/housewives) can inflate volume with weak purchasing power; check downstream.")
    if "Sales team capacity (1-hour contact)" in missed:
        points.append("Scaling volume must respect sales capacity (1-hour contact); 300-400 leads/day can overwhelm the team.")
    if campaign_metrics and campaign_metrics.get("hasData"):
        summary = campaign_metrics["summary"]
        points.append(
            f"Campaign reality: CPL ${summary.get('cpl', 0):,.2f}, lead rate {summary.get('leadRateFromClick', 0):.1f}% "
            f"from {summary.get('clicks', 0):,.0f} clicks — compare Meta AI's claims against this."
        )
    for lesson in (knowledge or {}).get("analysis", {}).get("lessons", [])[:2]:
        points.append(f"Knowledge base: {lesson}")
    return points


def analyze_capture(capture: dict[str, Any], *, knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    text = " ".join(
        part for part in [capture.get("sourceText", ""), capture.get("screenshotText", "")] if part
    ).strip()
    lower = text.lower()

    recommendations = extract_recommendations(text)
    evidence = [term for term in ADVISOR_EVIDENCE_TERMS if term in lower]
    numbers = _numbers(text)

    missed = [label for label, terms, _ in BUSINESS_SIGNAL_GROUPS if not any(term in lower for term in terms)]
    missed_critical = sum(
        1 for label, terms, critical in BUSINESS_SIGNAL_GROUPS if critical and not any(term in lower for term in terms)
    )

    campaign = None
    campaign_metrics = None
    if knowledge:
        lookup = capture.get("campaignName") or capture.get("campaignId") or text
        campaign = resolve_campaign(knowledge, str(lookup))
        if campaign:
            campaign_metrics = analyze_campaign(knowledge, campaign)

    scores = comparison_scores(
        text,
        recommendations,
        evidence,
        numbers,
        missed_critical,
        knowledge=knowledge,
        campaign_metrics=campaign_metrics,
    )
    trust = trust_level(scores, evidence, recommendations)

    advisor = {
        "recommendationSummary": recommendations or ["No explicit recommendation detected in the captured text."],
        "evidenceUsed": evidence,
        "whatItMissed": missed,
        "trustLevel": trust,
    }
    strategist = {
        "comparedAgainst": [
            "180-day Meta knowledge base" if knowledge else "Knowledge base not synced yet",
            f"Campaign metrics: {campaign['name']}" if campaign else "No specific campaign resolved",
            "Telegram/CRM tracking status",
            "Uzbekistan purchasing-power and sales-capacity context",
        ],
        "scores": scores,
        "overallScore": _clamp(sum(scores.values()) / len(scores)),
        "businessCounterpoints": _business_counterpoints(missed, knowledge, campaign_metrics),
        "campaign": campaign,
    }
    return {"advisor": advisor, "strategist": strategist}

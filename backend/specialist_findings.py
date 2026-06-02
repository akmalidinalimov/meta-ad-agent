"""Structured specialist findings computed from the saved Meta knowledge base.

Each specialist produces a real, evidence-scored finding (not a canned string):
ranked items, a confidence level, an evidence score that varies with sample size
and purchase proof, and concrete risks. These structured findings are the shared
substrate for proactive insights, agent-to-agent council debate, and dynamic
handoffs — so the agent layer reasons over the same real numbers everywhere.
"""

from __future__ import annotations

from typing import Any

from .analysis_engine import as_float, rank_dimension, summarize_overall, valid_rows
from .dashboard_service import tracking_calculations_from_knowledge

Finding = dict[str, Any]


def _base_rows(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return valid_rows((knowledge.get("raw", {}) or {}).get("insights", {}).get("base", []) or [])


def _analysis(knowledge: dict[str, Any]) -> dict[str, Any]:
    return knowledge.get("analysis", {}) or {}


def confidence_for(item: dict[str, Any] | None) -> str:
    if not item:
        return "low"
    clicks = as_float(item.get("clicks"))
    spend = as_float(item.get("spend"))
    if clicks >= 500 and spend >= 50:
        return "high"
    if clicks >= 100 and spend >= 10:
        return "medium"
    return "low"


def evidence_score(best: dict[str, Any] | None, item_count: int) -> float:
    """0-10 score that reflects how much real evidence backs the finding."""
    if not best:
        return 4.0
    base = {"high": 8.0, "medium": 6.5, "low": 5.0}[confidence_for(best)]
    if as_float(best.get("purchases")) > 0:
        base += 1.2  # downstream buyer proof is the strongest signal
    if item_count >= 3:
        base += 0.4
    return round(min(9.6, base), 1)


def _meaningful(item: dict[str, Any], min_spend: float) -> bool:
    return as_float(item.get("spend")) >= min_spend or as_float(item.get("clicks")) >= 500 or as_float(item.get("leads")) >= 100


def audience_findings(knowledge: dict[str, Any]) -> Finding:
    analysis = _analysis(knowledge)
    min_spend = max(5.0, analysis.get("summary", {}).get("spend", 0) * 0.02)
    adsets = rank_dimension(_base_rows(knowledge), ["adset_id", "adset_name"], limit=5)
    interests = [i for i in analysis.get("audience", {}).get("interests", []) if _meaningful(i, min_spend)][:5]
    best = adsets[0] if adsets else None
    risks: list[str] = []
    if best and not as_float(best.get("purchases")):
        risks.append("Top ad set has no attributed purchases — validate with Telegram START / CRM before scaling.")
    if not adsets:
        risks.append("No ad-set-level insight rows yet; resync Meta data for audience ranking.")
    headline = (
        f"Best ad set: {best['label']} (CPL ${as_float(best.get('cpl')):.2f}, "
        f"lead rate {as_float(best.get('leadRateFromClick')):.1f}%)"
        if best
        else "No meaningful audience evidence yet."
    )
    return {
        "agent": "audience",
        "headline": headline,
        "items": adsets,
        "interests": interests,
        "best": best,
        "confidence": confidence_for(best),
        "evidenceScore": evidence_score(best, len(adsets)),
        "risks": risks,
    }


def creative_findings(knowledge: dict[str, Any]) -> Finding:
    analysis = _analysis(knowledge)
    top_ads = [ad for ad in (analysis.get("topAds", []) or []) if _meaningful(ad, 5)][:5] or (analysis.get("topAds", []) or [])[:5]
    best = top_ads[0] if top_ads else None
    traffic_magnet = max(
        top_ads,
        key=lambda ad: (as_float(ad.get("leads")), as_float(ad.get("clicks"))),
        default=None,
    )
    weak_buyer = next((ad for ad in top_ads if as_float(ad.get("leads")) > 0 and as_float(ad.get("purchases")) == 0), None)
    risks: list[str] = []
    if weak_buyer is not None:
        risks.append(f"{_label(weak_buyer)} drives registrations but no attributed purchases — audit buyer quality.")
    headline = f"Top creative: {_label(best)}" if best else "No creative-level evidence yet."
    return {
        "agent": "creative",
        "headline": headline,
        "items": top_ads,
        "best": best,
        "trafficMagnet": traffic_magnet,
        "weakBuyer": weak_buyer,
        "confidence": confidence_for(best),
        "evidenceScore": evidence_score(best, len(top_ads)),
        "risks": risks,
    }


def placement_findings(knowledge: dict[str, Any]) -> Finding:
    analysis = _analysis(knowledge)
    min_spend = max(5.0, analysis.get("summary", {}).get("spend", 0) * 0.02)
    placements = [p for p in (analysis.get("placements", []) or []) if _meaningful(p, min_spend)]
    best = placements[0] if placements else None
    weak = max(placements, key=lambda p: (as_float(p.get("cpl")) or 1e9, as_float(p.get("spend"))), default=None)
    risks: list[str] = []
    if best and weak and best is not weak:
        risks.append(f"Isolate {weak['label']} — weaker cost/quality than {best['label']}.")
    headline = f"Best placement: {best['label']}" if best else "No placement breakdown synced yet."
    return {
        "agent": "placement",
        "headline": headline,
        "items": placements[:6],
        "best": best,
        "weak": weak,
        "confidence": confidence_for(best),
        "evidenceScore": evidence_score(best, len(placements)),
        "risks": risks,
    }


def funnel_findings(knowledge: dict[str, Any]) -> Finding:
    tracking = tracking_calculations_from_knowledge(knowledge)
    visit_rate = as_float(tracking.get("visitRatePercent"))
    landing_lead_rate = as_float(tracking.get("landingPageLeadRatePercent"))
    purchases = as_float(tracking.get("purchases"))
    risks: list[str] = []
    if visit_rate and visit_rate < 70:
        risks.append("Click-to-landing handoff is leaking (page speed / redirect / intent mismatch).")
    if landing_lead_rate and landing_lead_rate < 35:
        risks.append("Landing-to-registration is weak (promise / CTA / VSL-bot mismatch).")
    if not purchases:
        risks.append("No attributed purchases — connect Telegram START and CRM stages before scaling.")
    # Evidence score scales with how much click volume backs the funnel read.
    clicks = as_float(tracking.get("clicks"))
    score = 8.0 if clicks >= 1000 else 6.5 if clicks >= 200 else 5.0
    return {
        "agent": "funnel",
        "headline": f"Landing visit rate {visit_rate:.1f}%, landing→lead {landing_lead_rate:.1f}%",
        "tracking": tracking,
        "confidence": "high" if clicks >= 1000 else "medium" if clicks >= 200 else "low",
        "evidenceScore": round(score, 1),
        "risks": risks,
    }


def audit_findings(knowledge: dict[str, Any]) -> Finding:
    rows = _base_rows(knowledge)
    summary = summarize_overall(rows) if rows else _analysis(knowledge).get("summary", {})
    risks: list[str] = []
    if summary.get("leads") and not summary.get("purchases"):
        risks.append("Lead events exist but purchases are missing/unattributed — optimize cautiously.")
    score = 8.0 if as_float(summary.get("clicks")) >= 1000 else 6.0 if as_float(summary.get("clicks")) >= 200 else 5.0
    return {
        "agent": "audit",
        "headline": (
            f"Account: ${as_float(summary.get('spend')):,.0f} spend, {as_float(summary.get('leads')):,.0f} leads, "
            f"CPL ${as_float(summary.get('cpl')):.2f}"
        ),
        "summary": summary,
        "confidence": "high" if as_float(summary.get("clicks")) >= 1000 else "medium",
        "evidenceScore": round(score, 1),
        "risks": risks,
    }


def _label(item: dict[str, Any] | None) -> str:
    if not item:
        return "not enough data"
    keys = item.get("keys", {}) or {}
    return str(keys.get("ad_name") or item.get("label") or keys.get("ad_id") or "Unknown")


def collect_findings(knowledge: dict[str, Any] | None) -> dict[str, Finding]:
    """All specialist findings keyed by agent id. Empty dict when no knowledge."""
    if not knowledge:
        return {}
    return {
        "audit": audit_findings(knowledge),
        "audience": audience_findings(knowledge),
        "creative": creative_findings(knowledge),
        "placement": placement_findings(knowledge),
        "funnel": funnel_findings(knowledge),
    }

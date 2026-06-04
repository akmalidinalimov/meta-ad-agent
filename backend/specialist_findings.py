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
    attention = _attention_signals(top_ads)
    risks: list[str] = []
    if weak_buyer is not None:
        risks.append(f"{_label(weak_buyer)} drives registrations but no attributed purchases — audit buyer quality.")
    for note in attention.get("risks", []):
        risks.append(note)
    headline = f"Top creative: {_label(best)}" if best else "No creative-level evidence yet."
    if best is not None and best.get("hookRate") is not None:
        headline += f" (hook {as_float(best.get('hookRate')):.0f}%, hold {as_float(best.get('holdRate')):.0f}%)"
    return {
        "agent": "creative",
        "headline": headline,
        "items": top_ads,
        "best": best,
        "trafficMagnet": traffic_magnet,
        "weakBuyer": weak_buyer,
        "weakHook": attention.get("weakHook"),
        "weakHold": attention.get("weakHold"),
        "strongHook": attention.get("strongHook"),
        "confidence": confidence_for(best),
        "evidenceScore": evidence_score(best, len(top_ads)),
        "risks": risks,
    }


# Standard short-form thresholds: a >25% hook (3s view rate) and >50% hold (avg % watched)
# are healthy; below ~20% hook / ~30% hold flags weak attention worth a creative refresh.
HOOK_RATE_WEAK = 20.0
HOLD_RATE_WEAK = 30.0
HOOK_RATE_STRONG = 25.0


def _attention_signals(ads: list[dict[str, Any]]) -> dict[str, Any]:
    """Hook/hold-rate observations over video creatives. Degrades to empty when the
    video fields are absent (non-video account or fields not requested)."""
    with_video = [ad for ad in ads if ad.get("hookRate") is not None]
    if not with_video:
        return {}
    weak_hook = next(
        (ad for ad in with_video if as_float(ad.get("hookRate")) < HOOK_RATE_WEAK),
        None,
    )
    weak_hold = next(
        (ad for ad in with_video if ad.get("holdRate") is not None and as_float(ad.get("holdRate")) < HOLD_RATE_WEAK),
        None,
    )
    strong_hook = max(with_video, key=lambda ad: as_float(ad.get("hookRate")), default=None)
    if strong_hook is not None and as_float(strong_hook.get("hookRate")) < HOOK_RATE_STRONG:
        strong_hook = None
    risks: list[str] = []
    if weak_hook is not None:
        risks.append(
            f"{_label(weak_hook)} has a weak hook rate ({as_float(weak_hook.get('hookRate')):.0f}%) — the first 3s are not stopping the scroll."
        )
    if weak_hold is not None:
        risks.append(
            f"{_label(weak_hold)} has a weak hold rate ({as_float(weak_hold.get('holdRate')):.0f}%) — viewers drop off before the offer."
        )
    return {"weakHook": weak_hook, "weakHold": weak_hold, "strongHook": strong_hook, "risks": risks}


# A placement is only called "waste" when its CPL is materially worse than the best
# placement AND it is itself significant enough to trust the comparison. Below the margin
# it is within noise; below significance the CPL is not yet reliable.
PLACEMENT_WASTE_CPL_MARGIN = 1.4  # >40% worse CPL than the best placement


def placement_findings(knowledge: dict[str, Any]) -> Finding:
    analysis = _analysis(knowledge)
    min_spend = max(5.0, analysis.get("summary", {}).get("spend", 0) * 0.02)
    placements = [p for p in (analysis.get("placements", []) or []) if _meaningful(p, min_spend)]
    best = placements[0] if placements else None
    candidate = max(placements, key=lambda p: (as_float(p.get("cpl")) or 1e9, as_float(p.get("spend"))), default=None)

    # Significance gating: only flag the candidate as waste when (a) it is a different
    # placement than the best, (b) it clears the same confidence tiers used elsewhere
    # (not low), and (c) its CPL exceeds the best by a meaningful margin. Otherwise we
    # explicitly say there is no clear waste rather than naming a noisy loser.
    weak = None
    risks: list[str] = []
    if best is not None and candidate is not None and candidate is not best:
        best_cpl = as_float(best.get("cpl"))
        candidate_cpl = as_float(candidate.get("cpl"))
        significant = confidence_for(candidate) != "low"
        meaningful_margin = bool(best_cpl) and candidate_cpl > best_cpl * PLACEMENT_WASTE_CPL_MARGIN
        if significant and meaningful_margin:
            weak = candidate
            risks.append(
                f"Isolate {weak['label']} — CPL ${candidate_cpl:.2f} is more than "
                f"{int((PLACEMENT_WASTE_CPL_MARGIN - 1) * 100)}% above {best['label']} (${best_cpl:.2f})."
            )

    if best is None:
        headline = "No placement breakdown synced yet."
    elif weak is not None:
        headline = f"Best placement: {best['label']}"
    else:
        headline = f"Best placement: {best['label']} — no clear placement waste yet."
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
    cac = as_float(summary.get("costPerAcquisition"))
    cac_is_proxy = summary.get("cacIsProxy", True)
    if cac and cac_is_proxy:
        risks.append(
            f"CAC shown is a CPL proxy (${cac:.2f}); connect CRM/purchase data before treating it as a true customer acquisition cost."
        )
    score = 8.0 if as_float(summary.get("clicks")) >= 1000 else 6.0 if as_float(summary.get("clicks")) >= 200 else 5.0
    cac_phrase = (
        f"CAC ${cac:.2f}" + (" (CPL proxy)" if cac_is_proxy else "")
        if cac
        else "CAC unavailable"
    )
    cvr = summary.get("leadToPurchaseCvr")
    cvr_phrase = f", lead→purchase {as_float(cvr):.1f}%" if cvr is not None else ""
    return {
        "agent": "audit",
        "headline": (
            f"Account: ${as_float(summary.get('spend')):,.0f} spend, {as_float(summary.get('leads')):,.0f} leads, "
            f"CPL ${as_float(summary.get('cpl')):.2f}, {cac_phrase}{cvr_phrase}"
        ),
        "summary": summary,
        "leadToPurchaseCvr": cvr,
        "costPerAcquisition": cac or None,
        "cacIsProxy": cac_is_proxy,
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

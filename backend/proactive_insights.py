"""Proactive improvement insights derived from specialist findings.

Makes the agent layer proactive: instead of only answering when asked, it scans
the knowledge base and surfaces the highest-leverage issues unprompted (traffic
magnets with no buyers, funnel leaks, placement waste, unvalidated scale
candidates). Everything stays approval-safe — these are recommendations only.
"""

from __future__ import annotations

from typing import Any

from .analysis_engine import as_float
from .specialist_findings import collect_findings

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _insight(priority: str, agent: str, title: str, detail: str, action: str) -> dict[str, Any]:
    return {"priority": priority, "agent": agent, "title": title, "detail": detail, "suggestedAction": action}


def build_proactive_insights(knowledge: dict[str, Any] | None) -> list[dict[str, Any]]:
    findings = collect_findings(knowledge)
    if not findings:
        return []

    insights: list[dict[str, Any]] = []

    creative = findings.get("creative") or {}
    weak_buyer = creative.get("weakBuyer")
    if weak_buyer:
        keys = weak_buyer.get("keys", {}) or {}
        label = keys.get("ad_name") or weak_buyer.get("label") or "a top creative"
        insights.append(
            _insight(
                "high",
                "creative",
                f"Traffic magnet without buyers: {label}",
                f"{as_float(weak_buyer.get('leads')):,.0f} leads from {as_float(weak_buyer.get('clicks')):,.0f} clicks "
                "but no attributed purchases.",
                "Rework the first 3 seconds to qualify course value, or pair it with a higher-purchasing-power audience before scaling.",
            )
        )

    funnel = findings.get("funnel") or {}
    for risk in funnel.get("risks", []):
        if "purchases" in risk.lower():
            continue  # handled as a single tracking insight below
        insights.append(
            _insight("high", "funnel", "Funnel leak detected", risk, "Diagnose this step before increasing any budget.")
        )

    placement = findings.get("placement") or {}
    best, weak = placement.get("best"), placement.get("weak")
    if best and weak and best is not weak:
        insights.append(
            _insight(
                "medium",
                "placement",
                f"Placement waste: {weak['label']}",
                f"CPL ${as_float(weak.get('cpl')):.2f} vs {best['label']} at ${as_float(best.get('cpl')):.2f}.",
                f"Isolate or retarget-only on {weak['label']}; shift budget toward {best['label']} after quality checks.",
            )
        )

    audience = findings.get("audience") or {}
    audience_best = audience.get("best")
    if audience_best and not as_float(audience_best.get("purchases")):
        insights.append(
            _insight(
                "medium",
                "audience",
                f"Unvalidated scale candidate: {audience_best['label']}",
                f"Strongest CPL (${as_float(audience_best.get('cpl')):.2f}) but no purchase proof yet.",
                "Confirm Telegram START quality and CRM stage progression before scaling spend.",
            )
        )

    summary = (findings.get("audit") or {}).get("summary", {})
    if as_float(summary.get("leads")) and not as_float(summary.get("purchases")):
        insights.append(
            _insight(
                "medium",
                "funnel",
                "Purchase attribution missing",
                "Leads are tracked but no purchases are attributed, so rankings are lead/click-quality only.",
                "Connect Telegram START + CRM/Bitrix purchase stages so buyer quality can drive scaling decisions.",
            )
        )

    insights.sort(key=lambda item: _PRIORITY_RANK.get(item["priority"], 9))
    return insights

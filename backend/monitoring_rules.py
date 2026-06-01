from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def evaluate_monitoring_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    current = snapshot.get("current", {})
    previous = snapshot.get("previous", {})
    campaign_name = snapshot.get("campaignName") or "Unknown campaign"
    current_cpl = ratio(current.get("spend", 0), current.get("leads", 0))
    previous_cpl = ratio(previous.get("spend", 0), previous.get("leads", 0))
    current_cpc = ratio(current.get("spend", 0), current.get("clicks", 0))
    previous_cpc = ratio(previous.get("spend", 0), previous.get("clicks", 0))
    current_lead_rate = ratio(current.get("leads", 0), current.get("clicks", 0))
    previous_lead_rate = ratio(previous.get("leads", 0), previous.get("clicks", 0))
    current_start_rate = ratio(current.get("telegramStarts", 0), current.get("leads", 0))
    previous_start_rate = ratio(previous.get("telegramStarts", 0), previous.get("leads", 0))

    alerts: list[dict[str, Any]] = []
    if previous_cpl and current_cpl > previous_cpl * 1.35 and current_start_rate < previous_start_rate * 0.75:
        alerts.append(
            build_alert(
                snapshot,
                severity="high",
                title=f"CPL rose while Telegram START quality fell for {campaign_name}",
                why_it_matters="Costs are rising while downstream Telegram intent is weakening, which is the classic cheap-click-but-low-quality pattern.",
                metric_deltas={
                    "currentCpl": current_cpl,
                    "previousCpl": previous_cpl,
                    "currentStartRate": current_start_rate,
                    "previousStartRate": previous_start_rate,
                },
                recommended_actions=[
                    "Check if a cheap-click creative is attracting low-intent users.",
                    "Split Instagram placements from weak placements before scaling.",
                    "Hold budget increases until Telegram START rate recovers.",
                ],
            )
        )

    if previous_cpc and current_cpc > previous_cpc * 1.75:
        alerts.append(
            build_alert(
                snapshot,
                severity="medium",
                title=f"CPC rose quickly for {campaign_name}",
                why_it_matters="Traffic became more expensive. Before increasing budget, check whether creative fatigue, audience saturation, or placement mix changed.",
                metric_deltas={
                    "currentCpc": current_cpc,
                    "previousCpc": previous_cpc,
                    "currentClicks": current.get("clicks", 0),
                    "previousClicks": previous.get("clicks", 0),
                },
                recommended_actions=[
                    "Check whether frequency or creative fatigue is increasing.",
                    "Compare Instagram Reels, Stories, and Feed before changing budget.",
                    "Prepare a creative refresh test before scaling spend.",
                ],
            )
        )

    if previous_lead_rate and current_lead_rate < previous_lead_rate * 0.55 and current.get("spend", 0) >= previous.get("spend", 0) * 0.8:
        alerts.append(
            build_alert(
                snapshot,
                severity="medium",
                title=f"Lead rate dropped for {campaign_name}",
                why_it_matters="The campaign is still spending, but fewer clickers are becoming leads. This usually points to weaker audience intent, landing-page mismatch, or a creative promise that does not match the page.",
                metric_deltas={
                    "currentLeadRate": current_lead_rate,
                    "previousLeadRate": previous_lead_rate,
                    "currentSpend": current.get("spend", 0),
                    "previousSpend": previous.get("spend", 0),
                },
                recommended_actions=[
                    "Compare the current creative promise against the landing-page headline and Telegram/VSL promise.",
                    "Check if delivery shifted toward cheaper but lower-intent placements or regions.",
                    "Prepare a controlled creative or landing-page message test before scaling.",
                ],
            )
        )

    if current.get("spend", 0) >= 50 and current.get("clicks", 0) >= 150 and not current.get("leads", 0):
        alerts.append(
            build_alert(
                snapshot,
                severity="high",
                title=f"{campaign_name} has spend and clicks but no leads",
                why_it_matters="People are clicking but not registering. This is either a tracking problem, a landing-page/form problem, or a serious audience-message mismatch.",
                metric_deltas={
                    "currentSpend": current.get("spend", 0),
                    "currentClicks": current.get("clicks", 0),
                    "currentLeads": current.get("leads", 0),
                },
                recommended_actions=[
                    "Check landing page load speed, button click tracking, and form/Telegram link health immediately.",
                    "Verify Meta lead/registration events and Telegram START events are firing before interpreting traffic quality.",
                    "Do not increase budget until at least one lead path is confirmed working.",
                ],
            )
        )

    if current.get("leads", 0) and previous.get("leads", 0) and not current.get("telegramStarts", 0) and not previous.get("telegramStarts", 0):
        alerts.append(
            build_alert(
                snapshot,
                severity="medium",
                title=f"Telegram START tracking is missing for {campaign_name}",
                why_it_matters="Meta can show leads, but without Telegram START tracking we cannot tell whether leads enter the warm-up funnel.",
                metric_deltas={
                    "currentLeads": current.get("leads", 0),
                    "previousLeads": previous.get("leads", 0),
                    "currentTelegramStarts": current.get("telegramStarts", 0),
                    "previousTelegramStarts": previous.get("telegramStarts", 0),
                },
                recommended_actions=[
                    "Verify Telegram bot START webhook or ChatPlace event mapping.",
                    "Confirm landing Telegram links preserve visitor IDs.",
                    "Do not scale from Meta leads alone until START quality is visible.",
                ],
            )
        )

    return alerts


def build_alert(
    snapshot: dict[str, Any],
    *,
    severity: str,
    title: str,
    why_it_matters: str,
    metric_deltas: dict[str, Any],
    recommended_actions: list[str],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"alert_{snapshot.get('campaignId', 'unknown')}_{severity}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "campaignId": snapshot.get("campaignId"),
        "campaignName": snapshot.get("campaignName"),
        "severity": severity,
        "title": title,
        "whyItMatters": why_it_matters,
        "metricDeltas": metric_deltas,
        "recommendedActions": recommended_actions,
        "createdAt": now,
        "status": "open",
    }


def ratio(value: Any, base: Any) -> float:
    value_float = safe_float(value)
    base_float = safe_float(base)
    return 0 if not base_float else value_float / base_float


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0

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
    current_start_rate = ratio(current.get("telegramStarts", 0), current.get("leads", 0))
    previous_start_rate = ratio(previous.get("telegramStarts", 0), previous.get("leads", 0))

    alerts: list[dict[str, Any]] = []
    if previous_cpl and current_cpl > previous_cpl * 1.35 and current_start_rate < previous_start_rate * 0.75:
        alerts.append(
            build_alert(
                snapshot,
                severity="high",
                title=f"CPL rose while Telegram START quality fell for {campaign_name}",
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

    return alerts


def build_alert(
    snapshot: dict[str, Any],
    *,
    severity: str,
    title: str,
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

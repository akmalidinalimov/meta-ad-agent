from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def build_campaign_watch(dashboard_data: dict[str, Any], *, stale_days: int = 7) -> list[dict[str, Any]]:
    campaigns = {
        str(campaign.get("id")): campaign
        for campaign in dashboard_data.get("campaigns", [])
        if str(campaign.get("status", "active")).lower() in {"active", "paused"}
    }
    metrics = dashboard_data.get("metrics", [])
    latest_metric_date = latest_date(metrics)
    stale_before = latest_metric_date - timedelta(days=stale_days) if latest_metric_date else None
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for row in metrics:
        campaign_id = str(row.get("campaignId") or row.get("campaign_id") or "")
        date = str(row.get("date") or row.get("date_start") or "")
        if not campaign_id or not date or (campaigns and campaign_id not in campaigns):
            continue
        grouped.setdefault(campaign_id, {}).setdefault(date[:10], []).append(row)

    watch_rows = []
    for campaign_id, by_date in grouped.items():
        dates = sorted(by_date)
        if not dates:
            continue
        current_date = dates[-1]
        if stale_before and parse_date(current_date) < stale_before:
            continue
        previous_date = dates[-2] if len(dates) > 1 else None
        current = aggregate(by_date[current_date])
        previous = aggregate(by_date[previous_date]) if previous_date else {}
        campaign = campaigns.get(campaign_id, {})
        watch_rows.append(
            {
                "campaignId": campaign_id,
                "campaignName": campaign.get("name") or campaign_id,
                "status": campaign.get("status") or "unknown",
                "currentDate": current_date,
                "previousDate": previous_date,
                "daysObserved": len(dates),
                **metrics_for(current, previous),
            }
        )

    return sorted(watch_rows, key=lambda row: severity_rank(row["tone"]), reverse=True)[:12]


def metrics_for(current: dict[str, float], previous: dict[str, float]) -> dict[str, Any]:
    cpc = ratio(current.get("spend"), current.get("clicks"))
    cpl = ratio(current.get("spend"), current.get("leads"))
    lead_rate = ratio(current.get("leads"), current.get("clicks"))
    start_rate = ratio(current.get("telegramStarts"), current.get("leads"))
    previous_cpl = ratio(previous.get("spend"), previous.get("leads"))
    previous_lead_rate = ratio(previous.get("leads"), previous.get("clicks"))
    previous_start_rate = ratio(previous.get("telegramStarts"), previous.get("leads"))
    decision = campaign_decision(
        current=current,
        cpl=cpl,
        previous_cpl=previous_cpl,
        lead_rate=lead_rate,
        previous_lead_rate=previous_lead_rate,
        start_rate=start_rate,
        previous_start_rate=previous_start_rate,
    )
    return {
        "spendUsd": round(current.get("spend", 0), 2),
        "clicks": round(current.get("clicks", 0)),
        "leads": round(current.get("leads", 0)),
        "telegramStarts": round(current.get("telegramStarts", 0)),
        "cpc": cpc,
        "cpl": cpl,
        "leadRatePercent": lead_rate * 100,
        "telegramStartRatePercent": start_rate * 100,
        "previousCpl": previous_cpl,
        "previousLeadRatePercent": previous_lead_rate * 100,
        "decision": decision["decision"],
        "reason": decision["reason"],
        "tone": decision["tone"],
        "nextActions": decision["nextActions"],
    }


def campaign_decision(
    *,
    current: dict[str, float],
    cpl: float,
    previous_cpl: float,
    lead_rate: float,
    previous_lead_rate: float,
    start_rate: float,
    previous_start_rate: float,
) -> dict[str, Any]:
    if current.get("spend", 0) >= 50 and current.get("clicks", 0) >= 150 and not current.get("leads", 0):
        return decision(
            "Fix tracking or landing page before scaling",
            "Spend and clicks are present, but no leads are recorded.",
            "danger",
            [
                "Check landing-page load speed and primary button behavior.",
                "Verify Meta lead/registration and Telegram START events.",
                "Hold budget increases until at least one lead path is confirmed.",
            ],
        )

    if current.get("leads", 0) and not current.get("telegramStarts", 0):
        return decision(
            "Fix Telegram START tracking",
            "Leads exist, but Telegram START quality is invisible.",
            "warning",
            [
                "Confirm Telegram deep links preserve visitor IDs.",
                "Check bot START webhook or ChatPlace event mapping.",
                "Avoid scaling from Meta leads alone.",
            ],
        )

    if previous_lead_rate and lead_rate < previous_lead_rate * 0.55:
        return decision(
            "Investigate lead-rate drop",
            "Click-to-lead conversion fell sharply compared with the previous metric day.",
            "warning",
            [
                "Compare creative promise against landing-page/VSL message.",
                "Check if delivery shifted to weaker placements or regions.",
                "Prepare one controlled creative or landing-page message test.",
            ],
        )

    if previous_cpl and cpl > previous_cpl * 1.35:
        return decision(
            "Hold scaling and inspect CPL",
            "Cost per lead increased materially compared with the previous metric day.",
            "warning",
            [
                "Check frequency, creative fatigue, and placement mix.",
                "Do not increase budget until CPL stabilizes.",
                "Let the Experiment Agent propose one variable to test.",
            ],
        )

    if current.get("leads", 0) >= 10 and (not previous_start_rate or start_rate >= previous_start_rate * 0.8):
        return decision(
            "Continue monitoring",
            "Lead flow is present and Telegram START quality is not collapsing.",
            "good",
            [
                "Wait for more downstream quality before scaling.",
                "Compare creative/ad set rankings after the next check.",
                "Prepare a 20% scale proposal only if quality holds.",
            ],
        )

    return decision(
        "Collect more data",
        "The campaign has too little current evidence for a strong recommendation.",
        "neutral",
        [
            "Wait for the next monitoring interval.",
            "Check that all tracking events are firing.",
            "Avoid changing multiple variables at once.",
        ],
    )


def decision(decision_text: str, reason: str, tone: str, next_actions: list[str]) -> dict[str, Any]:
    return {
        "decision": decision_text,
        "reason": reason,
        "tone": tone,
        "nextActions": next_actions,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "spend": sum(number(row.get("spendUsd", row.get("spend", 0))) for row in rows),
        "clicks": sum(number(row.get("clicks", 0)) for row in rows),
        "leads": sum(number(row.get("leads", 0)) for row in rows),
        "telegramStarts": sum(number(row.get("telegramSubscribers", row.get("telegramStarts", 0))) for row in rows),
    }


def latest_date(rows: list[dict[str, Any]]) -> datetime | None:
    dates = [parse_date(str(row.get("date") or row.get("date_start") or "")) for row in rows]
    dates = [date for date in dates if date != datetime.min]
    return max(dates) if dates else None


def parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError:
        return datetime.min


def ratio(value: Any, base: Any) -> float:
    base_number = number(base)
    return 0 if not base_number else number(value) / base_number


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def severity_rank(tone: str) -> int:
    return {"danger": 3, "warning": 2, "neutral": 1, "good": 0}.get(tone, 1)

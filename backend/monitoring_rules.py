from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Cost rules (CPC/CPM/frequency) only fire once the current window has enough volume,
# so a single thin low-spend day cannot trip a noisy alarm.
COST_RULE_MIN_SPEND = 20.0
COST_RULE_MIN_CLICKS = 40
# Cold-prospecting frequency above this band means the same people are over-exposed.
FREQUENCY_FATIGUE_THRESHOLD = 2.8


def evaluate_monitoring_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    current = snapshot.get("current", {})
    previous = snapshot.get("previous", {})
    campaign_name = snapshot.get("campaignName") or "Unknown campaign"
    current_cpl = ratio(current.get("spend", 0), current.get("leads", 0))
    previous_cpl = ratio(previous.get("spend", 0), previous.get("leads", 0))
    current_cpc = ratio(current.get("spend", 0), current.get("clicks", 0))
    previous_cpc = ratio(previous.get("spend", 0), previous.get("clicks", 0))
    current_cpm = safe_float(current.get("cpm"))
    previous_cpm = safe_float(previous.get("cpm"))
    current_frequency = safe_float(current.get("frequency"))
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

    # Fallback quality alarm for the (current) reality where Telegram START tracking is
    # not connected, so telegramStarts is structurally 0 and the primary high-severity
    # rule above can never fire. CPL-rise + lead-rate-drop are signals that DO exist today.
    # Gated on the absence of any START signal so it never double-fires with the rule above.
    has_start_signal = bool(current.get("telegramStarts", 0) or previous.get("telegramStarts", 0))
    if (
        not has_start_signal
        and previous_cpl
        and current_cpl > previous_cpl * 1.35
        and previous_lead_rate
        and current_lead_rate < previous_lead_rate * 0.75
    ):
        alerts.append(
            build_alert(
                snapshot,
                severity="high",
                title=f"CPL rose while lead quality fell for {campaign_name}",
                why_it_matters="Cost per lead is climbing while the click-to-lead rate is dropping — the cheap-click-but-low-quality pattern. (Telegram START tracking is not connected, so this is judged on CPL and lead rate alone.)",
                metric_deltas={
                    "currentCpl": current_cpl,
                    "previousCpl": previous_cpl,
                    "currentLeadRate": current_lead_rate,
                    "previousLeadRate": previous_lead_rate,
                },
                recommended_actions=[
                    "Inspect the weakest ad set/placement driving the cheaper, lower-converting clicks.",
                    "Hold budget increases until the click-to-lead rate recovers.",
                    "Connect Telegram START tracking so buyer-quality, not just lead rate, can gate scaling.",
                ],
            )
        )

    # Cost rules require a minimum spend/clicks floor on the current window so a single
    # low-volume day (a few dollars, a handful of clicks) cannot trip a noisy cost alarm.
    cost_volume_ok = (
        safe_float(current.get("spend")) >= COST_RULE_MIN_SPEND
        and safe_float(current.get("clicks")) >= COST_RULE_MIN_CLICKS
    )

    # CPC trigger tightened from +75% to the +35-50% band so meaningful cost rises are
    # caught earlier, but only once the volume floor is met.
    if cost_volume_ok and previous_cpc and current_cpc > previous_cpc * 1.4:
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

    # CPM-rise companion to the CPC rule. Rising CPM at flat targeting is the auction-side
    # signal of audience saturation / fatigue, often before CPC moves. Only fires when both
    # windows report CPM and the volume floor is met.
    if cost_volume_ok and previous_cpm and current_cpm > previous_cpm * 1.4:
        alerts.append(
            build_alert(
                snapshot,
                severity="medium",
                title=f"CPM rose sharply for {campaign_name}",
                why_it_matters="Delivery is getting more expensive per impression, which usually means the auction is heating up from audience saturation or fatigue rather than a creative problem alone.",
                metric_deltas={
                    "currentCpm": current_cpm,
                    "previousCpm": previous_cpm,
                    "currentSpend": current.get("spend", 0),
                    "currentImpressions": current.get("impressions", 0),
                },
                recommended_actions=[
                    "Check audience overlap and frequency before adding budget.",
                    "Refresh or broaden the audience if CPM keeps climbing at the same targeting.",
                    "Rotate creative to reset auction relevance before scaling spend.",
                ],
            )
        )

    # Frequency-fatigue rule for cold prospecting: a frequency above ~2.5-3 on a prospecting
    # campaign means the same people are seeing the ads repeatedly, which drives CPM/CPC up
    # and quality down. Only fires when frequency is reported and the volume floor is met.
    if cost_volume_ok and current_frequency >= FREQUENCY_FATIGUE_THRESHOLD:
        alerts.append(
            build_alert(
                snapshot,
                severity="medium",
                title=f"Frequency fatigue building on {campaign_name}",
                why_it_matters="The same cold audience is seeing the ads too often, which inflates CPM/CPC and erodes response. This is the classic prospecting-fatigue pattern that precedes a CPL rise.",
                metric_deltas={
                    "currentFrequency": current_frequency,
                    "frequencyThreshold": FREQUENCY_FATIGUE_THRESHOLD,
                    "currentCpm": current_cpm,
                    "currentSpend": current.get("spend", 0),
                },
                recommended_actions=[
                    "Refresh creative or expand the cold audience to lower frequency.",
                    "Check whether CPM/CPC rose alongside the frequency climb.",
                    "Avoid budget increases until frequency comes back down.",
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

    if previous_cpl and current_cpl and current_cpl < previous_cpl * 0.75 and current_start_rate >= previous_start_rate * 0.9:
        alerts.append(
            build_alert(
                snapshot,
                severity="info",
                title=f"CPL improved while Telegram START quality held for {campaign_name}",
                why_it_matters="Costs are improving without an obvious downstream quality drop. This is a candidate for cautious scaling, not an automatic budget increase.",
                metric_deltas={
                    "currentCpl": current_cpl,
                    "previousCpl": previous_cpl,
                    "currentStartRate": current_start_rate,
                    "previousStartRate": previous_start_rate,
                },
                recommended_actions=[
                    "Prepare a 20% budget scale proposal if the next monitoring window confirms the same quality.",
                    "Check whether the improvement came from a specific creative, audience, or Instagram placement before scaling broadly.",
                    "Keep the change approval-gated and compare CRM lead quality before increasing spend.",
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

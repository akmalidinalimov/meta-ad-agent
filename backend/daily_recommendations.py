"""Pure decision engine for the Daily Funnel Analyst. Turns ranked audiences/creatives into
recommendations, honouring the QUALITY-OVER-VOLUME goal and a learning-phase guardrail (Meta
needs ~50 conversions to exit learning - don't recommend cuts before then)."""
from __future__ import annotations

from typing import Any

LEARNING_CONVERSIONS = 50
QUALITY_HIGH = 60   # audiences at/above are "quality" candidates to prioritize
QUALITY_LOW = 45    # cheap-but-shallow audiences to downweight

CPL_SPIKE_MULTIPLE = 2.0
ZERO_RESULT_SPEND_USD = 10.0


def _rec(action: str, target: str, rationale: str, goal_link: str, confidence: str) -> dict[str, Any]:
    return {"action": action, "target": target, "rationale": rationale,
            "goalLink": goal_link, "confidence": confidence}


def recommend(audiences: list[dict[str, Any]], *, total_conversions: int, targets: dict[str, Any]) -> list[dict[str, Any]]:
    """Audiences -> recommendations. Honours quality-over-volume; while in Meta's learning phase (total_conversions < LEARNING_CONVERSIONS) it emits leave_and_test and NEVER pause_creative."""
    learning = total_conversions < LEARNING_CONVERSIONS
    recs: list[dict[str, Any]] = []

    if learning:
        recs.append(_rec(
            "leave_and_test", "campaign",
            f"Only {total_conversions} conversions so far (<{LEARNING_CONVERSIONS}); still in "
            "Meta's learning phase. Hold changes; watch quality score + CPL over the next 2-3 days.",
            "Avoids resetting learning before the data is trustworthy.", "high"))

    ranked_q = sorted(audiences, key=lambda a: a.get("quality", 0), reverse=True)
    if ranked_q:
        best = ranked_q[0]
        if best.get("quality", 0) >= QUALITY_HIGH:
            recs.append(_rec(
                "prioritize_audience", best["adsetId"],
                f"{best['adsetName']} has the highest quality score ({best['quality']}) at CPL "
                f"${best.get('cpl')}. Shift budget toward it.",
                "Quality over volume: concentrate spend on the audience most likely to convert deep.",
                "medium" if learning else "high"))
        for aud in ranked_q:
            if aud.get("quality") is not None and aud["quality"] <= QUALITY_LOW and best.get("quality", 0) >= QUALITY_HIGH and aud["adsetId"] != best["adsetId"]:
                recs.append(_rec(
                    "downweight_audience", aud["adsetId"],
                    f"{aud['adsetName']} is cheap (CPL ${aud.get('cpl')}) but low quality "
                    f"({aud.get('quality')}) - likely shallow leads.",
                    "Quality over volume: cheap-but-shallow volume works against the goal.",
                    "medium"))

    if not learning:
        for aud in audiences:
            for ad in aud.get("creatives", {}).get("all", []):
                if "zero_result" in ad.get("flags", []):
                    recs.append(_rec(
                        "pause_creative", ad["adId"],
                        f"{ad['adName']} spent ${ad['spend']} over {ad['impressions']} impressions "
                        "with 0 leads (past the data floor). Pause to free budget for others.",
                        "Stops wasting spend so stronger creatives get delivery.", "high"))
                elif "fatigue" in ad.get("flags", []):
                    recs.append(_rec(
                        "refresh_creative", ad["adId"],
                        f"{ad['adName']} frequency is high - audience fatigue. Refresh the creative.",
                        "Fresh creative re-attracts high-intent users (resets audience exploration).",
                        "medium"))
    return recs


def detect_anomalies(today: dict[str, Any], baseline: dict[str, Any], *, targets: dict[str, Any]) -> list[dict[str, Any]]:
    """Intra-day guardrail checks for the 4-hourly cycle. Returns [] when healthy so the
    monitoring path only pings on a real problem (no notification fatigue)."""
    alerts: list[dict[str, Any]] = []
    cpl, base_cpl = today.get("cpl"), baseline.get("cpl")
    if cpl and base_cpl and cpl >= base_cpl * CPL_SPIKE_MULTIPLE:
        alerts.append({"kind": "cpl_spike", "message": f"CPL ${cpl} is {round(cpl / base_cpl, 1)}x the recent ${base_cpl}."})
    max_cpl = targets.get("maxCpl")
    if cpl and max_cpl and cpl > max_cpl:
        alerts.append({"kind": "cpl_over_target", "message": f"CPL ${cpl} is over your ${max_cpl} ceiling."})
    if not today.get("leads") and today.get("spend", 0) >= ZERO_RESULT_SPEND_USD:
        alerts.append({"kind": "zero_result_spend", "message": f"${today.get('spend')} spent today with 0 leads."})
    return alerts

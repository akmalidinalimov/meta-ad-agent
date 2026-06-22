"""Pure metric math for the Daily Funnel Analyst: per-ad metrics, per-audience
aggregation, the proxy quality score, and creative ranking. No I/O — everything is
computed from Meta insight rows passed in, so it is fully unit-testable."""
from __future__ import annotations

from statistics import median
from typing import Any

from .analysis_engine import count_conversion


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action_value(actions: Any, action_type: str) -> float:
    if not isinstance(actions, list):
        return 0.0
    for action in actions:
        if isinstance(action, dict) and action.get("action_type") == action_type:
            return safe_float(action.get("value"))
    return 0.0


def ad_metrics(row: dict[str, Any], *, conversion_event: str) -> dict[str, Any]:
    """Normalize one Meta ad-level insight row into the metrics the analyst ranks on."""
    spend = safe_float(row.get("spend"))
    impressions = safe_float(row.get("impressions"))
    leads = int(count_conversion(row, conversion_event))
    video_plays = _action_value(row.get("video_play_actions"), "video_view")
    p75 = _action_value(row.get("video_p75_watched_actions"), "video_view")
    hold_rate = (p75 / video_plays) if video_plays else 0.0
    return {
        "campaignId": str(row.get("campaign_id") or ""),
        "adsetId": str(row.get("adset_id") or ""),
        "adsetName": row.get("adset_name") or "",
        "adId": str(row.get("ad_id") or ""),
        "adName": row.get("ad_name") or "",
        "spend": round(spend, 2),
        "impressions": int(impressions),
        "leads": leads,
        "cpl": round(spend / leads, 2) if leads else None,
        "ctr": safe_float(row.get("ctr")),
        "frequency": safe_float(row.get("frequency")),
        "holdRate": hold_rate,
        "hasVideo": video_plays > 0,
    }


def aggregate_adsets(ad_rows: list[dict[str, Any]], *, conversion_event: str) -> list[dict[str, Any]]:
    """Group ad rows by ad set and sum into per-audience metrics (impression-weighted
    frequency/CTR so a big creative isn't out-voted by a tiny one)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in ad_rows:
        m = ad_metrics(row, conversion_event=conversion_event)
        groups.setdefault(m["adsetId"], []).append({**m, "_raw": row})
    out: list[dict[str, Any]] = []
    for adset_id, members in groups.items():
        spend = sum(m["spend"] for m in members)
        impressions = sum(m["impressions"] for m in members)
        leads = sum(m["leads"] for m in members)
        wfreq = (sum(m["frequency"] * m["impressions"] for m in members) / impressions) if impressions else 0.0
        wctr = (sum(m["ctr"] * m["impressions"] for m in members) / impressions) if impressions else 0.0
        video_members = [m for m in members if m["hasVideo"]]
        video_impr = sum(m["impressions"] for m in video_members)
        whold = (sum(m["holdRate"] * m["impressions"] for m in video_members) / video_impr) if video_impr else 0.0
        out.append({
            "adsetId": adset_id,
            "adsetName": members[0]["adsetName"],
            "campaignId": members[0]["campaignId"],
            "spend": round(spend, 2),
            "impressions": impressions,
            "leads": leads,
            "cpl": round(spend / leads, 2) if leads else None,
            "frequency": round(wfreq, 2),
            "ctr": round(wctr, 3),
            "holdRate": round(whold, 3),
            "adCount": len(members),
        })
    return out


def account_norms(adset_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Median CTR / CPL / hold across the audiences, so quality is judged against THIS
    account's own norms (Uzbek CPMs are a fraction of Western — never generic benchmarks)."""
    ctrs = [r["ctr"] for r in adset_rows if r["ctr"] > 0] or [0.0]
    cpls = [r["cpl"] for r in adset_rows if r["cpl"]] or [0.0]
    holds = [r["holdRate"] for r in adset_rows if r["holdRate"] > 0] or [0.0]
    return {"medianCtr": median(ctrs), "medianCpl": median(cpls), "medianHold": median(holds)}


# Data-sufficiency floor before a creative may be called a failure (Uzbek low-CPM tuned).
FLOORS = {"minImpressions": 500, "minSpendUsd": 2.0, "fatigueFrequency": 3.0}


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def quality_score(metric: dict[str, Any], norms: dict[str, float], *, account_start_rate: float) -> int:
    """0-100 ENGAGEMENT-PROXY quality (until per-audience CRM attribution is live). Weights:
    hold-rate 0.40 (depth = best proxy), CTR-vs-norm 0.25, low-frequency 0.15, START-vs-acct 0.20.
    Image ads (no hold) fold hold's weight into CTR so they aren't unfairly zeroed."""
    median_ctr = norms.get("medianCtr") or 1.0
    median_hold = norms.get("medianHold") or 0.3
    hold = _clamp01((metric.get("holdRate") or 0.0) / (median_hold * 1.5)) if metric.get("holdRate") else None
    ctr = _clamp01((metric.get("ctr") or 0.0) / (median_ctr * 1.5))
    freq = _clamp01((FLOORS["fatigueFrequency"] - (metric.get("frequency") or 1.0)) / (FLOORS["fatigueFrequency"] - 1.0))
    start = _clamp01((metric.get("startRate") or 0.0) / account_start_rate) if account_start_rate else 0.0
    if hold is None:
        score = 0.65 * ctr + 0.15 * freq + 0.20 * start    # no video -> redistribute hold weight to CTR
    else:
        score = 0.40 * hold + 0.25 * ctr + 0.15 * freq + 0.20 * start
    return round(100 * score)


def _flags(ad: dict[str, Any], norms: dict[str, float]) -> list[str]:
    flags: list[str] = []
    sufficient = ad["impressions"] >= FLOORS["minImpressions"] and ad["spend"] >= FLOORS["minSpendUsd"]
    if sufficient and ad["leads"] == 0:
        flags.append("zero_result")
    if (ad.get("frequency") or 0) >= FLOORS["fatigueFrequency"]:
        flags.append("fatigue")
    if norms.get("medianCtr") and ad["ctr"] < 0.5 * norms["medianCtr"]:
        flags.append("weak_hook")
    if sufficient and ad["cpl"] and norms.get("medianCpl") and ad["cpl"] > 2 * norms["medianCpl"]:
        flags.append("expensive")
    return flags


def rank_creatives(ad_metric_rows: list[dict[str, Any]], *, norms: dict[str, float]) -> dict[str, Any]:
    """Rank an audience's creatives by leads (volume proxy of delivery) then CPL; attach flags.
    Returns top-5 and the full annotated list."""
    annotated = [{**ad, "flags": _flags(ad, norms)} for ad in ad_metric_rows]
    ranked = sorted(annotated, key=lambda a: (a["leads"], -(a["cpl"] or 9e9)), reverse=True)
    return {"top": ranked[:5], "all": annotated}

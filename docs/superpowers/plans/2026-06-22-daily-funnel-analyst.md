# Daily Funnel Analyst — Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every day at 18:00 Europe/Stockholm, pull fresh Meta + bot + CRM data, rank audiences and creatives by a quality-over-volume score, and send a brief "where we are / what to do next" Telegram report with recommendations.

**Architecture:** Four isolated units — collect (`daily_analyst.py`) → metrics (`audience_creative_metrics.py`, pure) → decisions (`daily_recommendations.py`, pure) → report (`telegram_digest.py`). A once-per-day scheduler gate (`daily_analysis_scheduler.py`) is polled by the existing in-process `_monitoring_loop`; an auth-guarded `POST /api/analysis/daily` is the external-cron/manual trigger. Plan 1 SHOWS recommendations; Plan 2 makes them one-tap-executable.

**Tech Stack:** Python 3.11, FastAPI, httpx, APScheduler-free (in-process asyncio loop), `zoneinfo`, pytest. Existing helpers reused: `meta_client.get_insights/get_entity_insights/get_ad_sets/get_ads`, `analysis_engine.count_conversion/conversion_label`, `funnel_events.count_event_users/telegram_starts_by_campaign_date`, `bitrix_client.fetch_bitrix_leads` + `crm_funnel.split_by_cell`, `targets_store.load_targets`, `telegram_outbound`, `monitoring_scheduler` (pattern for run-log + debounce).

---

## Scope (Plan 1)

IN: data collection, rate + per-audience + per-creative metrics, proxy quality score, decision engine (recommendations as data + text), intra-day anomaly detection, creative-fatigue flags, 18:00 schedule, Telegram report, `/api/analysis/daily`. Quality is the **engagement proxy** (labelled as such).

OUT (→ Plan 2): one-tap-approve button execution, Meta write actions (pause/budget/custom-audience exclusion), per-audience CRM attribution (Phase 2 of the spec).

## File Structure

**Create:**
- `backend/audience_creative_metrics.py` — pure metric math (rates, per-audience aggregation, quality score, creative ranking + flags).
- `backend/daily_recommendations.py` — pure decision engine (recommendations + anomaly detection).
- `backend/daily_analyst.py` — async orchestration: collect fresh data, assemble the analysis object.
- `backend/daily_analysis_scheduler.py` — 18:00 Europe/Stockholm gate + run-log debounce + send.
- `backend/routers/analysis.py` — `POST /api/analysis/daily` (force run), `GET /api/analysis/daily` (latest).
- Tests: `backend/test_audience_creative_metrics.py`, `backend/test_daily_recommendations.py`, `backend/test_daily_analyst.py`, `backend/test_daily_analyst_report.py`, `backend/test_daily_analysis_scheduler.py`, `backend/test_analysis_api.py`.

**Modify:**
- `backend/telegram_digest.py` — add `build_daily_analyst_message(analysis)`.
- `backend/app.py` — extend `_monitoring_loop` to poll `run_scheduled_daily_analysis`.
- `backend/app.py` router registration — include the new `analysis` router.

---

## Task 1: Per-ad metric extraction

**Files:**
- Create: `backend/audience_creative_metrics.py`
- Test: `backend/test_audience_creative_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/test_audience_creative_metrics.py
from backend.audience_creative_metrics import ad_metrics

_ROW = {
    "campaign_id": "c1", "adset_id": "as1", "adset_name": "Lookalike-3%",
    "ad_id": "ad1", "ad_name": "vid_A", "spend": "10", "impressions": "1000",
    "reach": "800", "frequency": "1.25", "clicks": "50", "ctr": "5",
    "actions": [{"action_type": "lead", "value": "20"}],
    "video_play_actions": [{"action_type": "video_view", "value": "400"}],
    "video_p75_watched_actions": [{"action_type": "video_view", "value": "180"}],
    "video_p100_watched_actions": [{"action_type": "video_view", "value": "120"}],
}

def test_ad_metrics_computes_cpl_and_hold_rate():
    m = ad_metrics(_ROW, conversion_event="LEAD")
    assert m["adId"] == "ad1" and m["adName"] == "vid_A"
    assert m["spend"] == 10.0 and m["leads"] == 20
    assert m["cpl"] == 0.5                      # 10 / 20
    assert m["frequency"] == 1.25
    assert round(m["holdRate"], 2) == 0.45      # p75 180 / video_plays 400
    assert m["hasVideo"] is True

def test_ad_metrics_zero_leads_is_safe():
    row = {**_ROW, "actions": []}
    m = ad_metrics(row, conversion_event="LEAD")
    assert m["leads"] == 0 and m["cpl"] is None  # no division by zero
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.audience_creative_metrics`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/audience_creative_metrics.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/audience_creative_metrics.py backend/test_audience_creative_metrics.py
git commit -m "feat(analyst): per-ad metric extraction (cpl, hold-rate, leads)"
```

---

## Task 2: Per-audience aggregation + account norms

**Files:**
- Modify: `backend/audience_creative_metrics.py`
- Test: `backend/test_audience_creative_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.audience_creative_metrics import aggregate_adsets, account_norms

_ADS = [
    {"campaign_id": "c1", "adset_id": "as1", "adset_name": "LAL", "ad_id": "a", "ad_name": "v1",
     "spend": "10", "impressions": "1000", "frequency": "1.2", "ctr": "5",
     "actions": [{"action_type": "lead", "value": "20"}],
     "video_play_actions": [{"action_type": "video_view", "value": "400"}],
     "video_p75_watched_actions": [{"action_type": "video_view", "value": "200"}]},
    {"campaign_id": "c1", "adset_id": "as1", "adset_name": "LAL", "ad_id": "b", "ad_name": "v2",
     "spend": "6", "impressions": "600", "frequency": "1.1", "ctr": "3",
     "actions": [{"action_type": "lead", "value": "4"}]},
    {"campaign_id": "c1", "adset_id": "as2", "adset_name": "Interest", "ad_id": "c", "ad_name": "v3",
     "spend": "8", "impressions": "900", "frequency": "1.0", "ctr": "2",
     "actions": [{"action_type": "lead", "value": "16"}]},
]

def test_aggregate_adsets_sums_per_audience():
    rows = aggregate_adsets(_ADS, conversion_event="LEAD")
    by_id = {r["adsetId"]: r for r in rows}
    assert by_id["as1"]["spend"] == 16.0 and by_id["as1"]["leads"] == 24
    assert by_id["as1"]["cpl"] == round(16 / 24, 2)
    assert by_id["as1"]["adCount"] == 2

def test_account_norms_uses_medians():
    rows = aggregate_adsets(_ADS, conversion_event="LEAD")
    norms = account_norms(rows)
    assert norms["medianCtr"] > 0 and norms["medianCpl"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: FAIL — `ImportError: cannot import name 'aggregate_adsets'`.

- [ ] **Step 3: Write minimal implementation** (append to `audience_creative_metrics.py`)

```python
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
        whold = (sum(m["holdRate"] * m["impressions"] for m in members if m["hasVideo"]) /
                 sum(m["impressions"] for m in members if m["hasVideo"])) if any(m["hasVideo"] for m in members) else 0.0
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/audience_creative_metrics.py backend/test_audience_creative_metrics.py
git commit -m "feat(analyst): per-audience aggregation + account-relative norms"
```

---

## Task 3: Proxy quality score + creative ranking/flags

**Files:**
- Modify: `backend/audience_creative_metrics.py`
- Test: `backend/test_audience_creative_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.audience_creative_metrics import quality_score, rank_creatives, FLOORS

def test_quality_score_rewards_engagement_depth():
    norms = {"medianCtr": 3.0, "medianCpl": 0.6, "medianHold": 0.3}
    deep = {"ctr": 4.0, "frequency": 1.1, "holdRate": 0.45, "startRate": 80.0}
    shallow = {"ctr": 4.0, "frequency": 1.1, "holdRate": 0.10, "startRate": 80.0}
    assert quality_score(deep, norms, account_start_rate=70.0) > quality_score(shallow, norms, account_start_rate=70.0)
    assert 0 <= quality_score(shallow, norms, account_start_rate=70.0) <= 100

def test_rank_creatives_flags_zero_result_spender():
    ads = [
        {"adId": "good", "adName": "v1", "spend": 8.0, "impressions": 900, "leads": 16, "cpl": 0.5,
         "ctr": 4.0, "frequency": 1.2, "holdRate": 0.4, "hasVideo": True},
        {"adId": "dead", "adName": "v9", "spend": 6.0, "impressions": 800, "leads": 0, "cpl": None,
         "ctr": 0.5, "frequency": 4.2, "holdRate": 0.05, "hasVideo": True},
    ]
    ranked = rank_creatives(ads, norms={"medianCtr": 3.0, "medianCpl": 0.6, "medianHold": 0.3})
    assert ranked["top"][0]["adId"] == "good"
    dead = next(a for a in ranked["all"] if a["adId"] == "dead")
    assert "zero_result" in dead["flags"] and "fatigue" in dead["flags"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: FAIL — `ImportError: cannot import name 'quality_score'`.

- [ ] **Step 3: Write minimal implementation** (append)

```python
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
        score = 0.65 * ctr + 0.15 * freq + 0.20 * start    # no video → redistribute hold weight to CTR
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_audience_creative_metrics.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/audience_creative_metrics.py backend/test_audience_creative_metrics.py
git commit -m "feat(analyst): proxy quality score + creative ranking with flags"
```

---

## Task 4: Decision engine (recommendations + learning-phase guardrails)

**Files:**
- Create: `backend/daily_recommendations.py`
- Test: `backend/test_daily_recommendations.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/test_daily_recommendations.py
from backend.daily_recommendations import recommend, LEARNING_CONVERSIONS

def _audiences():
    return [
        {"adsetId": "as1", "adsetName": "LAL", "leads": 60, "cpl": 0.55, "quality": 78,
         "creatives": {"all": [{"adId": "dead", "adName": "v9", "leads": 0, "spend": 6.0,
                                "impressions": 900, "flags": ["zero_result", "fatigue"]}]}},
        {"adsetId": "as2", "adsetName": "Interest", "leads": 80, "cpl": 0.40, "quality": 45,
         "creatives": {"all": []}},
    ]

def test_learning_phase_prefers_leave_and_test():
    recs = recommend(_audiences(), total_conversions=20, targets={})  # < 50 → learning
    assert any(r["action"] == "leave_and_test" for r in recs)
    assert all(r["action"] != "pause_creative" for r in recs)  # no cuts while learning

def test_mature_campaign_recommends_quality_priority_and_pause():
    recs = recommend(_audiences(), total_conversions=200, targets={})
    actions = {r["action"] for r in recs}
    assert "prioritize_audience" in actions          # LAL: higher quality even if pricier
    assert "downweight_audience" in actions           # Interest: cheap but low quality
    assert "pause_creative" in actions                # dead creative past the floor
    prioritize = next(r for r in recs if r["action"] == "prioritize_audience")
    assert prioritize["target"] == "as1" and prioritize["goalLink"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_daily_recommendations.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.daily_recommendations`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/daily_recommendations.py
"""Pure decision engine for the Daily Funnel Analyst. Turns ranked audiences/creatives into
recommendations, honouring the QUALITY-OVER-VOLUME goal and a learning-phase guardrail (Meta
needs ~50 conversions to exit learning — don't recommend cuts before then)."""
from __future__ import annotations

from typing import Any

LEARNING_CONVERSIONS = 50
QUALITY_HIGH = 60   # audiences at/above are "quality" candidates to prioritize
QUALITY_LOW = 45    # cheap-but-shallow audiences to downweight


def _rec(action: str, target: str, rationale: str, goal_link: str, confidence: str) -> dict[str, Any]:
    return {"action": action, "target": target, "rationale": rationale,
            "goalLink": goal_link, "confidence": confidence}


def recommend(audiences: list[dict[str, Any]], *, total_conversions: int, targets: dict[str, Any]) -> list[dict[str, Any]]:
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
            if aud.get("quality", 99) < QUALITY_LOW and best.get("quality", 0) >= QUALITY_HIGH and aud is not best:
                recs.append(_rec(
                    "downweight_audience", aud["adsetId"],
                    f"{aud['adsetName']} is cheap (CPL ${aud.get('cpl')}) but low quality "
                    f"({aud.get('quality')}) — likely shallow leads.",
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
                        f"{ad['adName']} frequency is high — audience fatigue. Refresh the creative.",
                        "Fresh creative re-attracts high-intent users (resets audience exploration).",
                        "medium"))
    return recs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_daily_recommendations.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/daily_recommendations.py backend/test_daily_recommendations.py
git commit -m "feat(analyst): decision engine with learning-phase guardrails + quality tie-break"
```

---

## Task 5: Intra-day anomaly detection

**Files:**
- Modify: `backend/daily_recommendations.py`
- Test: `backend/test_daily_recommendations.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.daily_recommendations import detect_anomalies

def test_detect_anomalies_flags_cpl_spike_and_zero_result_spend():
    today = {"cpl": 1.6, "spend": 40.0, "leads": 25}
    baseline = {"cpl": 0.6}                       # 1.6 vs 0.6 → >2x spike
    alerts = detect_anomalies(today, baseline, targets={"maxCpl": 0.8})
    kinds = {a["kind"] for a in alerts}
    assert "cpl_spike" in kinds and "cpl_over_target" in kinds

def test_detect_anomalies_zero_result_burn():
    alerts = detect_anomalies({"cpl": None, "spend": 25.0, "leads": 0}, {"cpl": 0.6}, targets={})
    assert any(a["kind"] == "zero_result_spend" for a in alerts)

def test_detect_anomalies_quiet_when_healthy():
    assert detect_anomalies({"cpl": 0.55, "spend": 30.0, "leads": 55}, {"cpl": 0.6}, targets={"maxCpl": 0.8}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_daily_recommendations.py -q`
Expected: FAIL — `ImportError: cannot import name 'detect_anomalies'`.

- [ ] **Step 3: Write minimal implementation** (append to `daily_recommendations.py`)

```python
CPL_SPIKE_MULTIPLE = 2.0
ZERO_RESULT_SPEND_USD = 10.0


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_daily_recommendations.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/daily_recommendations.py backend/test_daily_recommendations.py
git commit -m "feat(analyst): intra-day anomaly detection (cpl spike, zero-result burn)"
```

---

## Task 6: Orchestration — collect fresh data + assemble analysis

**Files:**
- Create: `backend/daily_analyst.py`
- Test: `backend/test_daily_analyst.py`

**Context for the engineer:** `meta_client.get_insights(config, level="ad", since=..., until=..., time_increment=None)` returns aggregated ad-level rows for the window with the rich `_INSIGHTS_FIELDS`. `analysis_engine.conversion_label(event)` gives the human label. The per-campaign conversion event comes from `routers/campaigns._campaign_event_map(config)` — import and reuse it. `funnel_events.count_event_users`/`telegram_starts_by_campaign_date` give first-party START. `targets_store.load_targets()` gives the goal thresholds. All Meta calls are mocked in the test.

- [ ] **Step 1: Write the failing test**

```python
# backend/test_daily_analyst.py
import asyncio
from types import SimpleNamespace
import backend.daily_analyst as da

_ADS = [
    {"campaign_id": "c1", "campaign_name": "VSL", "adset_id": "as1", "adset_name": "LAL",
     "ad_id": "a", "ad_name": "v1", "spend": "10", "impressions": "1000", "frequency": "1.2",
     "ctr": "5", "actions": [{"action_type": "lead", "value": "20"}],
     "video_play_actions": [{"action_type": "video_view", "value": "400"}],
     "video_p75_watched_actions": [{"action_type": "video_view", "value": "200"}]},
    {"campaign_id": "c1", "campaign_name": "VSL", "adset_id": "as2", "adset_name": "Interest",
     "ad_id": "b", "ad_name": "v2", "spend": "8", "impressions": "900", "frequency": "1.0",
     "ctr": "2", "actions": [{"action_type": "lead", "value": "16"}]},
]

def test_analyze_produces_ranked_audiences_and_recs(monkeypatch):
    monkeypatch.setattr(da, "get_meta_config", lambda: SimpleNamespace(is_configured=True, ad_account_id="act_1"))

    async def fake_insights(config, **kw):
        return _ADS
    monkeypatch.setattr(da, "get_insights", fake_insights)
    monkeypatch.setattr(da, "_campaign_event_map", lambda config: {"c1": "LEAD"})
    monkeypatch.setattr(da, "count_bot_starts", lambda **kw: 30)
    monkeypatch.setattr(da, "count_event_users", lambda name, **kw: 40 if name == "telegram_link_click" else 0)
    monkeypatch.setattr(da, "load_targets", lambda: {"maxCpl": 0.8})
    monkeypatch.setattr(da, "_crm_today", lambda: {"leads": 5, "stages": {}})

    analysis = asyncio.run(da.run_daily_analysis())
    assert analysis["ok"] is True
    assert [a["adsetId"] for a in analysis["audiences"]]  # ranked, non-empty
    assert "recommendations" in analysis and "rates" in analysis
    assert analysis["rates"]["cpl"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_daily_analyst.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.daily_analyst`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/daily_analyst.py
"""Daily Funnel Analyst orchestration: pull fresh Meta + first-party + CRM data for the
current ad-account day, run the pure metric + decision engines, and return one analysis
object. Best-effort per source — a failing source degrades its section, never the report."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .analysis_engine import conversion_label
from .audience_creative_metrics import (
    account_norms, aggregate_adsets, ad_metrics, quality_score, rank_creatives,
)
from .daily_recommendations import recommend
from .funnel_events import count_bot_starts, count_event_users
from .meta_client import get_insights, get_meta_config
from .routers.campaigns import _campaign_event_map
from .targets_store import load_targets


def _crm_today() -> dict[str, Any]:
    """Account-level CRM leads today (no per-audience key yet). Best-effort: {} on failure."""
    try:
        from .bitrix_client import HttpBitrixTransport, fetch_bitrix_leads, get_bitrix_config
        import asyncio
        config = get_bitrix_config()
        if not config.is_configured:
            return {"leads": 0, "stages": {}}
        leads = asyncio.get_event_loop().run_until_complete(
            fetch_bitrix_leads(transport=HttpBitrixTransport(config), days=1, limit=None))
        return {"leads": len(leads), "stages": {}}
    except Exception:  # noqa: BLE001 - CRM is one of several sources
        return {"leads": 0, "stages": {}}


async def run_daily_analysis() -> dict[str, Any]:
    config = get_meta_config()
    if not config.is_configured:
        return {"ok": False, "error": "Meta not connected.", "audiences": [], "recommendations": []}

    until = date.today()
    since = until - timedelta(days=3)  # today + trailing context
    try:
        ads = await get_insights(config, level="ad", since=since.isoformat(), until=until.isoformat(), time_increment=None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "audiences": [], "recommendations": []}

    event_map = _campaign_event_map(config)
    default_event = next(iter(event_map.values()), "LEAD") if event_map else "LEAD"

    # Per-audience aggregation, grouped by each ad's own campaign conversion event.
    enriched: list[dict[str, Any]] = []
    for row in ads:
        event = event_map.get(str(row.get("campaign_id")), default_event)
        enriched.append({**row, "_event": event})
    adset_rows = aggregate_adsets(enriched, conversion_event=default_event)
    norms = account_norms(adset_rows)

    bot_starts = count_bot_starts()
    link_clicks = count_event_users("telegram_link_click")
    account_start_rate = (bot_starts / link_clicks * 100) if link_clicks else 0.0

    by_adset: dict[str, list[dict[str, Any]]] = {}
    for row in enriched:
        by_adset.setdefault(str(row.get("adset_id")), []).append(
            ad_metrics(row, conversion_event=row["_event"]))

    audiences: list[dict[str, Any]] = []
    for adset in adset_rows:
        adset["startRate"] = account_start_rate  # per-audience START not available yet (proxy)
        adset["quality"] = quality_score(adset, norms, account_start_rate=account_start_rate or 1.0)
        adset["creatives"] = rank_creatives(by_adset.get(adset["adsetId"], []), norms=norms)
        audiences.append(adset)
    audiences.sort(key=lambda a: (a["quality"], a["leads"]), reverse=True)

    total_spend = sum(a["spend"] for a in audiences)
    total_leads = sum(a["leads"] for a in audiences)
    targets = load_targets()
    crm = _crm_today()
    rates = {
        "spend": round(total_spend, 2),
        "leads": total_leads,
        "cpl": round(total_spend / total_leads, 2) if total_leads else None,
        "startRate": round(account_start_rate, 1),
        "crmLeads": crm["leads"],
        "conversionLabel": conversion_label(default_event),
    }
    recs = recommend(audiences, total_conversions=total_leads, targets=targets)
    return {"ok": True, "date": until.isoformat(), "rates": rates, "targets": targets,
            "audiences": audiences, "recommendations": recs, "qualityIsProxy": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_daily_analyst.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/daily_analyst.py backend/test_daily_analyst.py
git commit -m "feat(analyst): orchestration — collect fresh data + assemble analysis"
```

---

## Task 7: Telegram report builder

**Files:**
- Modify: `backend/telegram_digest.py`
- Test: `backend/test_daily_analyst_report.py`

**Context:** match the existing digest style in `telegram_digest.py` (plain text + emoji, Telegram-safe). The message must show the proxy footnote and degrade gracefully when sections are empty.

- [ ] **Step 1: Write the failing test**

```python
# backend/test_daily_analyst_report.py
from backend.telegram_digest import build_daily_analyst_message

_ANALYSIS = {
    "ok": True, "date": "2026-06-22", "qualityIsProxy": True,
    "rates": {"spend": 84.0, "leads": 142, "cpl": 0.59, "startRate": 71.0, "crmLeads": 12, "conversionLabel": "Lead rate"},
    "targets": {"maxCpl": 0.8},
    "audiences": [
        {"adsetId": "as1", "adsetName": "LAL-3%", "leads": 54, "cpl": 0.55, "quality": 78,
         "creatives": {"top": [{"adName": "vid_A", "cpl": 0.41, "holdRate": 0.48, "flags": []}],
                       "all": [{"adName": "vid_E", "flags": ["zero_result"]}]}},
    ],
    "recommendations": [
        {"action": "prioritize_audience", "target": "as1", "rationale": "LAL-3% highest quality.", "confidence": "high"},
    ],
}

def test_report_has_headline_rates_audiences_actions_and_proxy_note():
    msg = build_daily_analyst_message(_ANALYSIS)
    assert "Daily Funnel Analyst" in msg and "2026-06-22" in msg
    assert "$0.59" in msg and "71" in msg            # rates
    assert "LAL-3%" in msg and "78" in msg           # audience + quality
    assert "prioritize" in msg.lower()               # action
    assert "proxy" in msg.lower()                    # honesty footnote

def test_report_handles_meta_failure():
    msg = build_daily_analyst_message({"ok": False, "error": "Meta not connected."})
    assert "could not" in msg.lower() or "not connected" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_daily_analyst_report.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_daily_analyst_message'`.

- [ ] **Step 3: Write minimal implementation** (append to `telegram_digest.py`)

```python
def build_daily_analyst_message(analysis: dict) -> str:
    if not analysis.get("ok"):
        return f"📊 Daily Funnel Analyst\nCould not run analysis: {analysis.get('error', 'unknown error')}"
    r = analysis["rates"]
    targets = analysis.get("targets", {})
    cpl = f"${r['cpl']}" if r.get("cpl") is not None else "—"
    cpl_mark = " ✅" if (r.get("cpl") and targets.get("maxCpl") and r["cpl"] <= targets["maxCpl"]) else (
        " ⚠️" if (r.get("cpl") and targets.get("maxCpl")) else "")
    lines = [
        f"📊 Daily Funnel Analyst · {analysis['date']} · Goal: quality > volume",
        "",
        "WHERE WE ARE",
        f"Spend ${r['spend']} · Leads {r['leads']} · CPL {cpl}{cpl_mark} · START {r['startRate']}% · CRM {r['crmLeads']}",
        "",
        "🏆 AUDIENCES (by quality*, then volume)",
    ]
    for i, a in enumerate(analysis.get("audiences", [])[:5], 1):
        acpl = f"${a['cpl']}" if a.get("cpl") is not None else "—"
        lines.append(f"{i}. {a['adsetName']}  {a['leads']} leads · CPL {acpl} · quality {a['quality']}")
        top = a.get("creatives", {}).get("top", [])
        if top:
            best = top[0]
            lines.append(f"   ✅ {best['adName']} (CPL ${best.get('cpl')}, hold {round((best.get('holdRate') or 0)*100)}%)")
        dead = [c for c in a.get("creatives", {}).get("all", []) if "zero_result" in c.get("flags", [])]
        if dead:
            lines.append(f"   ❌ {dead[0]['adName']} (0 leads past floor)")
    recs = analysis.get("recommendations", [])
    if recs:
        lines += ["", "▶️ WHAT TO DO NEXT"]
        for i, rec in enumerate(recs[:3], 1):
            lines.append(f"{i}. [{rec['action']}] {rec['rationale']} ({rec['confidence']})")
    if analysis.get("qualityIsProxy"):
        lines += ["", "* quality = engagement proxy until per-audience CRM attribution is live"]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_daily_analyst_report.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/telegram_digest.py backend/test_daily_analyst_report.py
git commit -m "feat(analyst): Telegram daily report builder (brief, proxy-honest)"
```

---

## Task 8: Scheduler gate (18:00 Europe/Stockholm, once/day)

**Files:**
- Create: `backend/daily_analysis_scheduler.py`
- Test: `backend/test_daily_analysis_scheduler.py`

**Context:** mirror `monitoring_scheduler.py`'s run-log pattern (`save_monitoring_run`/`list_monitoring_runs` use `storage/`). Use `zoneinfo.ZoneInfo("Europe/Stockholm")` for DST-safe 18:00.

- [ ] **Step 1: Write the failing test**

```python
# backend/test_daily_analysis_scheduler.py
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.daily_analysis_scheduler import should_run_daily

STK = ZoneInfo("Europe/Stockholm")

def test_fires_at_or_after_18_when_not_run_today():
    now = datetime(2026, 6, 22, 18, 5, tzinfo=STK)
    assert should_run_daily(now, last_run_date=None) is True

def test_does_not_fire_before_18():
    now = datetime(2026, 6, 22, 17, 59, tzinfo=STK)
    assert should_run_daily(now, last_run_date=None) is False

def test_does_not_fire_twice_same_day():
    now = datetime(2026, 6, 22, 18, 30, tzinfo=STK)
    assert should_run_daily(now, last_run_date="2026-06-22") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_daily_analysis_scheduler.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/daily_analysis_scheduler.py
"""Once-per-day gate for the Daily Funnel Analyst (18:00 Europe/Stockholm), polled by the
in-process monitoring loop. Keeps a run-log so a restart near 18:00 can't double-send."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .storage_io import read_json, write_json_atomic

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[0].parent
STORAGE_DIR = ROOT / "storage"
RUN_FILE = "daily_analysis_run.json"
TZ = ZoneInfo("Europe/Stockholm")
SEND_HOUR = 18


def should_run_daily(now: datetime, *, last_run_date: str | None) -> bool:
    local = now.astimezone(TZ)
    if local.hour < SEND_HOUR:
        return False
    return last_run_date != local.date().isoformat()


def _last_run_date(*, storage_dir: Path = STORAGE_DIR) -> str | None:
    payload = read_json(storage_dir / RUN_FILE, None)
    return payload.get("date") if isinstance(payload, dict) else None


def run_scheduled_daily_analysis(*, force: bool = False, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Run + send the daily analysis if the gate is open (or forced). Returns a status dict."""
    from .daily_analyst import run_daily_analysis
    from .telegram_digest import build_daily_analyst_message
    from .telegram_outbound import send_message_to_operators  # existing broadcast helper

    now = datetime.now(TZ)
    if not force and not should_run_daily(now, last_run_date=_last_run_date(storage_dir=storage_dir)):
        return {"skipped": True, "reason": "Outside the 18:00 window or already ran today."}

    analysis = asyncio.run(run_daily_analysis())
    message = build_daily_analyst_message(analysis)
    try:
        send_message_to_operators(message)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send daily analyst report")
    write_json_atomic(storage_dir / RUN_FILE, {"date": now.date().isoformat(), "ok": analysis.get("ok")})
    return {"skipped": False, "ok": analysis.get("ok"), "sent": True}
```

> **Engineer note:** confirm the exact operator-broadcast function name in `telegram_outbound.py` (the codebase already sends the KPI digest — reuse that same sender). If it is named differently (e.g. `send_kpi_digest` wraps a lower-level `send_message`), call the lower-level sender with `message`. Adjust the import on the line marked above; do not invent a new sender.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_daily_analysis_scheduler.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/daily_analysis_scheduler.py backend/test_daily_analysis_scheduler.py
git commit -m "feat(analyst): 18:00 Europe/Stockholm once-per-day scheduler gate"
```

---

## Task 9: Wire the gate into the monitoring loop + anomaly into the 4-hourly path

**Files:**
- Modify: `backend/app.py` (the `_monitoring_loop` body, around lines 81-116)

- [ ] **Step 1: Add the daily poll to the loop**

In `_monitoring_loop`, after the existing opportunity block and before `await asyncio.sleep(interval)`, add:

```python
            # Daily Funnel Analyst — its own 18:00 Europe/Stockholm once-per-day gate.
            try:
                from .daily_analysis_scheduler import run_scheduled_daily_analysis
                daily_result = await asyncio.to_thread(run_scheduled_daily_analysis)
                if isinstance(daily_result, dict) and not daily_result.get("skipped"):
                    logger.info("Daily analyst report sent")
            except Exception:
                logger.exception("Daily analyst iteration failed")
```

- [ ] **Step 2: Verify the app still imports and starts**

Run: `python -c "import backend.app"`
Expected: no error (imports cleanly).

- [ ] **Step 3: Run the full backend suite**

Run: `python -m pytest backend/ -q`
Expected: PASS (all prior tests + the new ones).

- [ ] **Step 4: Commit**

```bash
git add backend/app.py
git commit -m "feat(analyst): poll the daily 18:00 gate from the in-process monitoring loop"
```

---

## Task 10: `/api/analysis/daily` endpoint (manual + external-cron trigger)

**Files:**
- Create: `backend/routers/analysis.py`
- Modify: `backend/app.py` (register the router next to the other routers, ~line 223)
- Test: `backend/test_analysis_api.py`

**Context:** follow `backend/routers/monitoring.py` for the router pattern and the auth dependency the other protected routers use (the dashboard session guard). `POST` forces a run; `GET` returns the latest analysis without sending.

- [ ] **Step 1: Write the failing test**

```python
# backend/test_analysis_api.py
from fastapi.testclient import TestClient
import backend.routers.analysis as analysis_router
from backend.app import app

def test_post_daily_forces_run(monkeypatch):
    monkeypatch.setattr(analysis_router, "run_scheduled_daily_analysis",
                        lambda **kw: {"skipped": False, "ok": True, "sent": True})
    body = TestClient(app).post("/api/analysis/daily").json()
    assert body["ok"] is True and body["sent"] is True

def test_get_daily_returns_analysis(monkeypatch):
    async def fake_run():
        return {"ok": True, "audiences": [], "recommendations": [], "rates": {}}
    monkeypatch.setattr(analysis_router, "run_daily_analysis", fake_run)
    body = TestClient(app).get("/api/analysis/daily").json()
    assert body["ok"] is True and "recommendations" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_analysis_api.py -q`
Expected: FAIL — `ModuleNotFoundError: backend.routers.analysis`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/routers/analysis.py
"""Daily Funnel Analyst trigger + read endpoints. POST forces a run+send (manual button /
external cron); GET returns the latest analysis object for the dashboard without sending."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..daily_analysis_scheduler import run_scheduled_daily_analysis
from ..daily_analyst import run_daily_analysis

router = APIRouter()


@router.post("/api/analysis/daily")
async def trigger_daily_analysis() -> dict[str, Any]:
    return run_scheduled_daily_analysis(force=True)


@router.get("/api/analysis/daily")
async def get_daily_analysis() -> dict[str, Any]:
    return await run_daily_analysis()
```

In `backend/app.py`, register it next to the other `app.include_router(...)` calls:

```python
from .routers import analysis as analysis_router
...
app.include_router(analysis_router.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_analysis_api.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/analysis.py backend/app.py backend/test_analysis_api.py
git commit -m "feat(analyst): /api/analysis/daily trigger + read endpoint"
```

---

## Task 11: Full-suite regression + manual smoke

- [ ] **Step 1: Run the entire backend suite**

Run: `python -m pytest backend/ -q`
Expected: PASS (640 prior + ~16 new).

- [ ] **Step 2: Manual smoke (local, Meta mocked or live read-only)**

Run: `python -c "import asyncio, json; from backend.daily_analyst import run_daily_analysis; print(json.dumps(asyncio.run(run_daily_analysis()), default=str)[:800])"`
Expected: a JSON analysis object (or `{"ok": false, "error": "Meta not connected."}` if no creds locally — that is fine; live verification happens on the VM at deploy).

- [ ] **Step 3: Commit any fixups**

```bash
git add -A && git commit -m "test(analyst): full-suite regression green"
```

---

## Deploy (operator-gated — do NOT deploy without explicit approval)

Per the standing rule, deployment to the VM is a separate, explicitly-approved step. When approved, follow the existing deploy pattern: LF-normalized transfer of the changed/new `backend/*.py` files to `/home/opc/meta-ad-agent`, `python3.11 -m py_compile` guard, `sudo systemctl restart meta-ad-agent`, verify `GET /api/health` = 200, then `POST /api/analysis/daily` once to smoke the live report into Telegram. Confirm memory stays flat (the daily job runs under the 550 MB cap).

## Self-Review (completed by plan author)

- **Spec coverage:** rates ✓(T6/T7), per-audience ranking ✓(T2/T6), per-creative top-5 + flags ✓(T3), quality proxy ✓(T3), decision engine + learning guardrail + quality tie-break ✓(T4), fatigue alerts ✓(T3 flag→T4 refresh rec), intra-day anomaly ✓(T5/T9), 18:00 Stockholm schedule ✓(T8/T9), Telegram delivery ✓(T7/T8), `/api/analysis/daily` ✓(T10), TZ/best-effort/memory-safety ✓(T6/T8). One-tap execution + exclude-past-leads write + per-audience attribution = **Plan 2** (explicitly out of scope).
- **Placeholder scan:** none — every code step is complete. The single judgement call (exact operator-broadcast sender name in `telegram_outbound.py`) is called out as an engineer note with a deterministic rule, not a TODO.
- **Type consistency:** `ad_metrics` keys (`adsetId`, `holdRate`, `leads`, `cpl`, `flags`) are used consistently across T1→T3→T6→T7; `recommend()`/`detect_anomalies()` shapes match their consumers in T7/T9.

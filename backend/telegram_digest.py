"""Recurring KPI digest for Telegram.

The 4-hourly monitoring loop only messaged Telegram when a rule tripped, so a calm
account produced silence. This module builds the full KPI table that is pushed every
monitoring cycle (and on the 📊 KPIs → "Show KPIs now" button) so the operator always
sees exactly what the web dashboard shows — the same numbers, never a different,
inconsistent set.

It deliberately reuses the dashboard's own live sources so the two surfaces can never
disagree: the per-campaign KPI bundle (/api/campaigns/kpis → Meta), the CRM stage
breakdown (/api/crm/stages → Bitrix), and the VSL watch-through (/api/vsl → YouTube).
The rate + cost math mirrors the dashboard's simpleFunnel.ts exactly (capped at 100%,
rounded the same way). All reads are read-only; live writes are unaffected.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any

# 90 days covers the full lifetime of the account's current campaigns, so the digest
# reads as "total overall performance" rather than a misleadingly short window.
DIGEST_WINDOW_DAYS = 90


# --- formatting + math helpers (rate/cost mirror src/components/simpleFunnel.ts) -----


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _int(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def _rate(numer: Any, denom: Any) -> float:
    """Step conversion as a 1-decimal percent, capped at 100% — identical to the
    dashboard's pct(): Math.min(100, round(numer/denom * 1000) / 10)."""
    try:
        numer_f = float(numer)
        denom_f = float(denom)
    except (TypeError, ValueError):
        return 0.0
    if denom_f > 0:
        return min(100.0, round((numer_f / denom_f) * 1000) / 10)
    return 0.0


def _cost(spend: Any, count: Any) -> float:
    """Spend ÷ a stage's volume, rounded to cents — identical to the dashboard's money()."""
    try:
        spend_f = float(spend)
        count_f = float(count)
    except (TypeError, ValueError):
        return 0.0
    if count_f > 0:
        return round((spend_f / count_f) * 100) / 100
    return 0.0


def _marker(actual: Any, target: Any, direction: str) -> str:
    """ ✅/ ⚠️ suffix comparing an actual KPI to an operator target. Empty when no
    target is set. direction 'max' = actual should be <= target (cost KPIs);
    'min' = actual should be >= target (rate KPIs)."""
    if target is None or actual is None:
        return ""
    try:
        actual_f = float(actual)
        target_f = float(target)
    except (TypeError, ValueError):
        return ""
    ok = actual_f <= target_f if direction == "max" else actual_f >= target_f
    return " ✅" if ok else " ⚠️"


def _rate_str(value: float) -> str:
    return f"{value:.1f}%"


SPARK_CHARS = "▁▂▃▄▅▆▇█"
# Rates rendered in the TREND (7d) block, in funnel order.
_TREND_RATES = (
    ("Visit rate", "visit"),
    ("Lead rate", "lead"),
    ("Start rate", "start"),
    ("VSL view rate", "vslView"),
    ("CRM fill rate", "crmFill"),
)


def _sparkline(values: list[float | None]) -> str:
    """A unicode block sparkline for a 0–100% series. Missing days render as '·'."""
    out: list[str] = []
    for value in values:
        if value is None:
            out.append("·")
            continue
        clamped = max(0.0, min(100.0, float(value)))
        out.append(SPARK_CHARS[int(round(clamped / 100 * (len(SPARK_CHARS) - 1)))])
    return "".join(out) if out else "—"


def _trend_arrow(values: list[float | None]) -> str:
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return ""
    delta = nums[-1] - nums[0]
    return "↑" if delta > 1 else "↓" if delta < -1 else "→"


def _rate_series(points: list[dict[str, Any]], key: str) -> list[float | None]:
    """Per-day values for one rate, derived from the history points with the SAME math as
    the dashboard cards (so the sparkline and the headline agree). VSL is None on days with
    no snapshot delta so the sparkline shows a gap, not a misleading 0."""
    series: list[float | None] = []
    for point in points:
        counts = point.get("counts", {}) or {}
        if key == "visit":
            series.append(_rate(counts.get("landingViews"), counts.get("linkClicks")))
        elif key == "lead":
            series.append(_rate(counts.get("leads"), counts.get("landingViews")))
        elif key == "start":
            series.append(float(point.get("startRate", 0) or 0))
        elif key == "vslView":
            vsl_views = counts.get("vslViews")
            series.append(None if vsl_views is None else _rate(vsl_views, counts.get("botStarts")))
        elif key == "crmFill":
            series.append(_rate(counts.get("crmLeads"), counts.get("botStarts")))
    return series


def _build_trend_rows(history: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """The TREND (7d) rows: (label, sparkline, "↑ first→last%"). Rates with no data in the
    window (e.g. VSL before snapshots accrue) read 'accruing'."""
    last7 = history[-7:]
    rows: list[tuple[str, str, str]] = []
    for label, key in _TREND_RATES:
        series = _rate_series(last7, key)
        non_null = [v for v in series if v is not None]
        if not non_null:
            rows.append((label, "accruing", ""))
            continue
        note = f"{_trend_arrow(series)} {non_null[0]:.0f}→{non_null[-1]:.0f}%".strip()
        rows.append((label, _sparkline(series), note))
    return rows


def _render_table(sections: list[tuple[str, list[tuple[str, str, str]]]]) -> str:
    """Render labelled sections into one monospace block (Telegram <pre>). Labels and
    values are padded to a single global width so every section's columns line up."""
    all_rows = [row for _, rows in sections for row in rows]
    label_w = max((len(row[0]) for row in all_rows), default=0)
    value_w = max((len(row[1]) for row in all_rows), default=0)
    lines: list[str] = []
    for index, (title, rows) in enumerate(sections):
        if index:
            lines.append("")
        lines.append(title)
        for label, value, note in rows:
            line = f"{label.ljust(label_w)}  {value.rjust(value_w)}"
            if note:
                line += f"   {note}"
            lines.append(line)
    return "\n".join(lines)


# --- live data gathering (the SAME sources the web dashboard uses) --------------------


async def _gather_digest_data(
    campaign_id: str | None, days: int = DIGEST_WINDOW_DAYS
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fetch the dashboard's three live sources concurrently and return
    (kpis, crm, vsl). Each call falls back to a safe empty shape so one failing
    source (e.g. YouTube not connected) never blanks the whole digest."""
    from .routers.campaigns import campaign_kpis
    from .routers.crm import crm_stages
    from .routers.vsl import vsl_metrics

    async def _safe(coro: Any, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            return await coro
        except Exception:  # noqa: BLE001 - a single source failing must not break the digest
            return fallback

    kpis, crm, vsl = await asyncio.gather(
        _safe(campaign_kpis(campaignId=campaign_id, days=days, force=True), {"ok": False}),
        _safe(crm_stages(days=days, force=True), {"ok": False, "total": 0, "stages": []}),
        _safe(vsl_metrics(days=days, force=True), {"ok": False, "configured": False, "views": None}),
    )
    return kpis, crm, vsl


async def _gather_history(campaign_id: str | None, days: int = 7) -> list[dict[str, Any]]:
    """The last ``days`` days of per-day funnel points for the in-chat trend sparklines.
    Best-effort: any failure yields [] so the digest still renders without a trend block."""
    from .routers.funnel import funnel_history

    try:
        result = await funnel_history(campaignId=campaign_id, days=days, force=True)
    except Exception:  # noqa: BLE001 - sparklines are a bonus, never break the digest
        return []
    return result.get("points", []) if result.get("ok") else []


# --- digest rendering -----------------------------------------------------------------


def format_full_digest(
    kpis: dict[str, Any],
    crm: dict[str, Any],
    vsl: dict[str, Any],
    *,
    selection: dict[str, Any] | None = None,
    pending: int = 0,
    targets: dict[str, Any] | None = None,
    days: int = DIGEST_WINDOW_DAYS,
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Render the full KPI digest from the dashboard's live bundles. parse_mode must be
    "HTML" when sending. Sections: RATES (visit / lead / start / VSL-view / CRM-fill),
    COST PER STEP, VOLUME, and the CRM stage breakdown — everything the dashboard shows."""
    targets = targets or {}
    kpis = kpis or {}
    crm = crm or {}
    vsl = vsl or {}

    k = kpis.get("kpis") or {}
    counts = kpis.get("counts") or {}
    rates = kpis.get("rates") or {}
    meta_ok = bool(kpis.get("ok"))
    has_data = bool(kpis.get("hasData"))

    spend = float(k.get("spend", 0) or 0)
    impressions = float(k.get("impressions", 0) or 0)
    reach = float(k.get("reach", 0) or 0)
    link_clicks = float(counts.get("linkClicks", 0) or 0)
    landing_views = float(counts.get("landingPageViews", 0) or 0)
    leads = float(counts.get("leads", 0) or 0)
    bot_starts = float(counts.get("botStarts", 0) or 0)
    tg_link_clicks = float(counts.get("telegramLinkClicks", 0) or 0)
    # START rate is the backend's select_start_rate (first-party bot starts ÷ Telegram
    # button clicks) — the deliberate one the dashboard's Start card uses — NOT starts/leads.
    start_rate = float(rates.get("startRate", 0) or 0)
    start_denom_src = kpis.get("startDenominatorSource")
    start_scope = kpis.get("startScope")

    vsl_configured = bool(vsl.get("configured"))
    vsl_views = float(vsl.get("views") or 0)
    watch_rate50 = vsl.get("watchRate50")
    has_retention = bool(vsl.get("hasRetention"))

    crm_ok = bool(crm.get("ok"))
    crm_total = float(crm.get("total", 0) or 0) if crm_ok else 0.0

    # Rates — mirror the dashboard's five cards exactly.
    visit_rate = _rate(landing_views, link_clicks)
    lead_rate = _rate(leads, landing_views)
    vsl_rate = _rate(vsl_views, bot_starts)
    crm_rate = _rate(crm_total, bot_starts)

    # Cost per step — spend ÷ each stage's volume.
    cost_visit = _cost(spend, landing_views)
    cost_lead = _cost(spend, leads)
    cost_start = _cost(spend, bot_starts)
    cost_vsl = _cost(spend, vsl_views)
    cost_crm = _cost(spend, crm_total)

    start_denom = (
        f"{_int(tg_link_clicks)} button clicks"
        if start_denom_src == "telegram_link_click"
        else f"{_int(leads)} leads"
    )
    start_note = f"{_int(bot_starts)} starts ÷ {start_denom}"
    # When a campaign is pinned but bot-starts can only be attributed account-wide, flag it.
    if start_scope == "account" and selection:
        start_note += " · account-wide"

    rates_rows: list[tuple[str, str, str]] = [
        ("Visit rate", _rate_str(visit_rate), f"{_int(landing_views)} views ÷ {_int(link_clicks)} clicks"),
        (
            "Lead rate",
            _rate_str(lead_rate) + _marker(lead_rate, targets.get("minLeadRate"), "min"),
            f"{_int(leads)} leads ÷ {_int(landing_views)} views",
        ),
        (
            "Start rate",
            _rate_str(start_rate) + _marker(start_rate, targets.get("minStartRate"), "min"),
            start_note,
        ),
    ]
    if vsl_configured:
        rates_rows.append(
            ("VSL view rate", _rate_str(vsl_rate), f"{_int(vsl_views)} views ÷ {_int(bot_starts)} starts")
        )
    else:
        rates_rows.append(("VSL view rate", "—", "connect YouTube to populate"))
    rates_rows.append(("CRM fill rate", _rate_str(crm_rate), f"{_int(crm_total)} CRM ÷ {_int(bot_starts)} starts"))
    if has_retention and watch_rate50 is not None:
        rates_rows.append(("VSL 50% watched", _rate_str(float(watch_rate50)), "of YouTube viewers"))

    cost_rows: list[tuple[str, str, str]] = [
        ("Per visit", _money(cost_visit), ""),
        ("Per lead", _money(cost_lead) + _marker(cost_lead, targets.get("maxCpl"), "max"), ""),
        ("Per bot start", _money(cost_start) + _marker(cost_start, targets.get("maxCostPerStart"), "max"), ""),
        ("Per VSL view", _money(cost_vsl) if vsl_configured else "—", ""),
        ("Per CRM lead", _money(cost_crm) if crm_ok else "—", ""),
    ]

    vol_rows: list[tuple[str, str, str]] = [
        ("Spend", _money(spend), ""),
        ("Impressions", _int(impressions), ""),
        ("Reach", _int(reach), ""),
        ("Link clicks", _int(link_clicks), ""),
        ("Landing views", _int(landing_views), ""),
        ("Leads (CTA)", _int(leads), ""),
        ("Bot starts", _int(bot_starts), ""),
        ("VSL views", _int(vsl_views) if vsl_configured else "—", ""),
        ("CRM leads", _int(crm_total) if crm_ok else "—", ""),
    ]

    sections: list[tuple[str, list[tuple[str, str, str]]]] = [
        ("RATES", rates_rows),
        ("COST PER STEP", cost_rows),
        ("VOLUME", vol_rows),
    ]

    # In-chat 7-day trend sparklines (so the operator sees direction without opening the
    # web dashboard). Inserted right after RATES.
    if history:
        trend_rows = _build_trend_rows(history)
        if trend_rows:
            sections.insert(1, ("TREND (7d)", trend_rows))

    if crm_ok and crm_total > 0:
        stage_rows: list[tuple[str, str, str]] = []
        for stage in crm.get("stages") or []:
            cnt = float(stage.get("count", 0) or 0)
            if cnt <= 0:
                continue
            pct = round(cnt / crm_total * 100)
            stage_rows.append((str(stage.get("name") or stage.get("id") or "—"), _int(cnt), f"{pct}%"))
        if stage_rows:
            title = "CRM STAGES"
            src = crm.get("source")
            if src:
                title += f" — {src}"
            sections.append((title[:60], stage_rows[:10]))

    table = _render_table(sections)

    if selection:
        scope = f"campaign: {selection.get('campaignName') or selection.get('campaignId')}"
    else:
        scope = "account-wide"
    if not meta_ok:
        state = "⚠️ live data unavailable"
    elif not has_data:
        state = "no delivery in this window yet"
    else:
        state = "live"
    subtitle = f"{scope} · {state} · last {days} days"

    parts = [
        "<b>📊 Meta Ad Agent — KPI digest</b>",
        f"<i>{html.escape(subtitle)}</i>",
        f"<pre>{html.escape(table)}</pre>",
    ]
    if pending:
        parts.append(f"🤖 {pending} suggestion(s) waiting for your review.")
    parts.append("Reply in chat to test, change, or apply. Live writes stay off until you confirm.")
    return "\n".join(parts)


def compose_kpi_digest_text() -> str:
    """Render the full KPI digest from LIVE dashboard data (Meta + Bitrix + YouTube).

    Account-wide by default; when the operator has pinned a campaign (Telegram KPI
    panel) the digest scopes to it and the subtitle names it. Runs the async fetch via
    asyncio.run, which is SAFE here because the digest is composed from a sync route
    handler (FastAPI threadpool — no running loop) or the monitoring loop's worker
    thread — the same pattern the rest of the Telegram surface uses.
    """
    from .approval_store import list_approval_requests
    from .kpi_digest_campaign_store import load_kpi_digest_campaign
    from .targets_store import load_targets

    targets = load_targets()
    pending = sum(1 for approval in list_approval_requests() if approval.get("status") == "needs_review")
    selection = load_kpi_digest_campaign()
    campaign_id = selection.get("campaignId") if selection else None

    kpis, crm, vsl = asyncio.run(_gather_digest_data(campaign_id, DIGEST_WINDOW_DAYS))
    history = asyncio.run(_gather_history(campaign_id, days=7))
    return format_full_digest(
        kpis,
        crm,
        vsl,
        selection=selection,
        pending=pending,
        targets=targets,
        days=DIGEST_WINDOW_DAYS,
        history=history,
    )


def send_kpi_digest() -> dict[str, Any]:
    """Compose and push the KPI digest to the admin Telegram chat (HTML formatted)."""
    from .telegram_outbound import send_telegram_message_sync

    text = compose_kpi_digest_text()
    return send_telegram_message_sync(text, parse_mode="HTML")


# --- Daily Funnel Analyst report -------------------------------------------------------


def build_daily_analyst_message(analysis: dict) -> str:
    """Build a plain-text Telegram message from a daily analysis dict.

    Designed to be brief and operator-actionable: headline rates, top audiences
    ranked by quality (engagement proxy until per-audience CRM attribution is live),
    top/dead creatives per audience, and up to 3 prioritised recommendations.
    """
    if not analysis.get("ok"):
        return (
            f"📊 Daily Funnel Analyst\n"
            f"Could not run analysis: {analysis.get('error', 'unknown error')}"
        )

    r = analysis["rates"]
    targets = analysis.get("targets", {})

    cpl = f"${r['cpl']}" if r.get("cpl") is not None else "—"
    if r.get("cpl") is not None and targets.get("maxCpl") is not None:
        cpl_mark = " ✅" if r["cpl"] <= targets["maxCpl"] else " ⚠️"
    else:
        cpl_mark = ""

    lines = [
        f"📊 Daily Funnel Analyst · {analysis['date']} · Goal: quality > volume",
        "",
        "WHERE WE ARE",
        (
            f"Spend ${r['spend']} · Leads {r['leads']} · "
            f"CPL {cpl}{cpl_mark} · START {r['startRate']}% · CRM {r['crmLeads']}"
        ),
        "",
        "🏆 AUDIENCES (by quality*, then volume)",
    ]

    for i, a in enumerate(analysis.get("audiences", [])[:5], 1):
        acpl = f"${a['cpl']}" if a.get("cpl") is not None else "—"
        lines.append(
            f"{i}. {a['adsetName']}  {a['leads']} leads · CPL {acpl} · quality {a['quality']}"
        )
        top = a.get("creatives", {}).get("top", [])
        if top:
            best = top[0]
            hold_pct = round((best.get("holdRate") or 0) * 100)
            lines.append(f"   ✅ {best['adName']} (CPL ${best.get('cpl')}, hold {hold_pct}%)")
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

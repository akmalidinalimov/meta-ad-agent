"""Recurring KPI digest for Telegram.

The 4-hourly monitoring loop only messaged Telegram when a rule tripped, so a calm
account produced silence. This module builds a compact "heartbeat" KPI table that is
pushed every monitoring cycle regardless of alerts, so the operator always sees how the
account is performing. It reuses the already-computed analysis summary + funnel rates;
no new metric math. Live writes are unaffected — this is read-only reporting.
"""

from __future__ import annotations

import html
from typing import Any


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


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


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


def build_kpi_rows(
    summary: dict[str, Any],
    funnel: dict[str, Any],
    targets: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """The 7 KPIs shown in the digest, as (label, value) pairs.

    summary = knowledge["analysis"]["summary"] (from analysis_engine.summarize_overall);
    funnel  = funnel_events.build_funnel_summary();
    targets = targets_store.load_targets() (optional; adds ✅/⚠️ vs goal).
    """
    summary = summary or {}
    funnel = funnel or {}
    targets = targets or {}
    rates = funnel.get("rates", {}) or {}

    spend = float(summary.get("spend", 0) or 0)
    leads = float(summary.get("leads", 0) or 0)
    purchases = float(summary.get("purchases", 0) or 0)
    starts = float(funnel.get("uniqueTelegramUsers", 0) or 0)
    cost_per_start = (spend / starts) if starts else None
    cpl = summary.get("cpl", 0)
    lead_rate = summary.get("leadRateFromClick", 0)
    start_rate = rates.get("telegramStartRate", 0)

    return [
        ("Spend (90d)", _money(spend)),
        ("Leads", f"{_int(leads)}  (CPL {_money(cpl)}){_marker(cpl, targets.get('maxCpl'), 'max')}"),
        ("Lead rate", f"{_pct(lead_rate)}{_marker(lead_rate, targets.get('minLeadRate'), 'min')}"),
        ("CTR", _pct(summary.get("ctr", 0))),
        (
            "Telegram STARTs",
            _int(starts)
            + (
                f"  ({_money(cost_per_start)}/start){_marker(cost_per_start, targets.get('maxCostPerStart'), 'max')}"
                if cost_per_start is not None
                else "  (no events yet)"
            ),
        ),
        ("START rate", f"{_pct(start_rate)}{_marker(start_rate, targets.get('minStartRate'), 'min')}"),
        (
            "Purchases",
            _int(purchases) + ("  (tracking gap)" if not purchases else f"  (CPP {_money(summary.get('cpp', 0))})"),
        ),
    ]


def format_kpi_digest(
    summary: dict[str, Any],
    funnel: dict[str, Any],
    *,
    pending_approvals: int = 0,
    subtitle: str | None = None,
    targets: dict[str, Any] | None = None,
) -> str:
    """Build the Telegram HTML message body. parse_mode must be set to "HTML" when sending."""
    rows = build_kpi_rows(summary, funnel, targets)
    width = max((len(label) for label, _ in rows), default=0)
    table = "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)

    parts = ["<b>📊 Meta Ad Agent — KPI digest</b>"]
    if subtitle:
        parts.append(f"<i>{html.escape(subtitle)}</i>")
    parts.append(f"<pre>{html.escape(table)}</pre>")
    if pending_approvals:
        parts.append(f"🤖 {pending_approvals} suggestion(s) waiting for your review.")
    parts.append("Reply in chat to test, change, or apply. Live writes stay off until you confirm.")
    return "\n".join(parts)


DIGEST_WINDOW_DAYS = 90


def _live_meta_summary(campaign_id: str | None, days: int = DIGEST_WINDOW_DAYS) -> tuple[dict[str, Any], bool, bool]:
    """LIVE Meta KPI summary (summarize_overall shape) for one campaign or the whole
    account, fetched fresh from Meta — NOT the stale synced knowledge base. Returns
    (summary, hasData, available). ``available`` is False when Meta is not configured or
    the live fetch failed, so the digest can say "live data unavailable" instead of
    mislabelling a fetch failure as "no delivery yet".

    Runs the async insight fetch via asyncio.run, which is SAFE here because the digest
    is composed either from a sync Telegram handler (no running event loop) or from the
    monitoring loop's ``asyncio.to_thread`` worker (a thread with no running loop) — the
    same pattern routers/telegram._live_account_sync uses.
    """
    import asyncio

    from .analysis_engine import summarize_overall, valid_rows
    from .meta_client import get_meta_config
    from .meta_sync import safe_chunked_insights

    config = get_meta_config()
    if not config.is_configured:
        return {}, False, False
    try:
        raw = asyncio.run(safe_chunked_insights(config, "kpi_digest", None, days=days))
    except Exception:  # noqa: BLE001 - never let a live-fetch failure break the digest
        return {}, False, False
    account_rows = valid_rows(raw)
    had_errors = any(isinstance(row, dict) and row.get("sync_error") for row in raw)
    if not account_rows and had_errors:
        return {}, False, False  # Meta reachable but every window errored — not "no delivery"
    rows = (
        [row for row in account_rows if str(row.get("campaign_id")) == str(campaign_id)]
        if campaign_id
        else account_rows
    )
    return summarize_overall(rows), bool(rows), True


def _campaign_funnel(summary: dict[str, Any]) -> dict[str, Any]:
    """A funnel-shaped dict for build_kpi_rows scoped to one campaign.

    The first-party funnel summary is account-wide and not reliably campaign-attributed,
    so the scoped digest uses Meta's per-campaign 'subscribe' (bot-start) conversions for
    the STARTs row, with START rate = subscribes / leads (capped)."""
    from .analysis_engine import ratio

    starts = float(summary.get("subscribes", 0) or 0)
    leads = float(summary.get("leads", 0) or 0)
    return {
        "uniqueTelegramUsers": starts,
        "rates": {"telegramStartRate": min(100.0, ratio(starts, leads) * 100)},
    }


def compose_kpi_digest_text() -> str:
    """Render the KPI digest from LIVE Meta data (always current, not a stale snapshot).

    Account-wide by default. When the operator has pinned a campaign (Telegram KPI
    panel), the digest is scoped to that campaign — fetched live so a brand-new / just-
    running campaign reports correctly — and the subtitle names it. A pinned campaign
    with no delivery yet honestly shows zeros with a "no delivery yet" note rather than
    silently falling back to the account total.
    """
    from .approval_store import list_approval_requests
    from .funnel_events import build_funnel_summary
    from .kpi_digest_campaign_store import load_kpi_digest_campaign
    from .targets_store import load_targets

    targets = load_targets()
    pending = sum(1 for approval in list_approval_requests() if approval.get("status") == "needs_review")
    selection = load_kpi_digest_campaign()

    if selection:
        summary, has_rows, available = _live_meta_summary(selection["campaignId"])
        funnel = _campaign_funnel(summary)
        name = selection.get("campaignName") or selection["campaignId"]
        scope_label = f"campaign: {name}"
        if not available:
            state = "⚠️ live data unavailable (Meta fetch failed)"
        elif not has_rows:
            state = "no delivery in this window yet"
        else:
            state = "live"
    else:
        summary, _has_rows, available = _live_meta_summary(None)
        funnel = build_funnel_summary()
        scope_label = "account-wide"
        state = "live" if available else "⚠️ live data unavailable (Meta fetch failed)"

    subtitle = f"{scope_label} · {state} · last {DIGEST_WINDOW_DAYS} days"
    return format_kpi_digest(summary, funnel, pending_approvals=pending, subtitle=subtitle, targets=targets)


def send_kpi_digest() -> dict[str, Any]:
    """Compose and push the KPI digest to the admin Telegram chat (HTML formatted)."""
    from .telegram_outbound import send_telegram_message_sync

    text = compose_kpi_digest_text()
    return send_telegram_message_sync(text, parse_mode="HTML")

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


def _campaign_summary(knowledge: dict[str, Any], campaign_id: str) -> tuple[dict[str, Any], str] | None:
    """(summary, campaign_name) scoped to one campaign, or None when that campaign has
    no rows in the latest synced knowledge base (e.g. brand-new / no delivery yet).

    Reuses analysis_engine.summarize_overall on just that campaign's base insight rows,
    so the scoped summary has the exact same shape/fields as the account summary — no
    new metric math, and CPL/lead-rate/CTR/purchases stay consistent with the dashboard.
    """
    from .analysis_engine import summarize_overall, valid_rows

    base_rows = ((knowledge.get("raw") or {}).get("insights") or {}).get("base", [])
    rows = [row for row in valid_rows(base_rows) if str(row.get("campaign_id")) == str(campaign_id)]
    if not rows:
        return None
    name = next((str(row.get("campaign_name")) for row in rows if row.get("campaign_name")), "")
    return summarize_overall(rows), name


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
    """Load the latest synced analysis + live funnel and render the digest text.

    Account-wide by default. When the operator has pinned a campaign (Telegram KPI
    panel), the digest is scoped to that campaign and the subtitle names it, so it is
    always clear which campaign the numbers describe.
    """
    from .approval_store import list_approval_requests
    from .funnel_events import build_funnel_summary
    from .knowledge_base import load_knowledge_base
    from .kpi_digest_campaign_store import load_kpi_digest_campaign
    from .targets_store import load_targets

    knowledge = load_knowledge_base() or {}
    targets = load_targets()
    pending = sum(1 for approval in list_approval_requests() if approval.get("status") == "needs_review")
    generated_at = (knowledge.get("snapshot") or {}).get("generatedAt")

    selection = load_kpi_digest_campaign()
    scoped = _campaign_summary(knowledge, selection["campaignId"]) if selection else None

    if scoped:
        summary, resolved_name = scoped
        funnel = _campaign_funnel(summary)
        name = resolved_name or selection.get("campaignName") or selection["campaignId"]
        scope_label = f"campaign: {name}"
    else:
        summary = (knowledge.get("analysis") or {}).get("summary", {})
        funnel = build_funnel_summary()
        scope_label = (
            "account-wide (pinned campaign not in latest sync yet)" if selection else "account-wide"
        )

    pieces = [scope_label, "last 90 days"] + ([f"synced {generated_at}"] if generated_at else [])
    subtitle = " · ".join(pieces)
    return format_kpi_digest(summary, funnel, pending_approvals=pending, subtitle=subtitle, targets=targets)


def send_kpi_digest() -> dict[str, Any]:
    """Compose and push the KPI digest to the admin Telegram chat (HTML formatted)."""
    from .telegram_outbound import send_telegram_message_sync

    text = compose_kpi_digest_text()
    return send_telegram_message_sync(text, parse_mode="HTML")

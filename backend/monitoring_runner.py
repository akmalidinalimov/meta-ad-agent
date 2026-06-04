from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .monitoring_rules import evaluate_monitoring_snapshot
from .storage_io import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
ALERTS_PATH = STORAGE_DIR / "monitoring_alerts.json"

AlertSender = Callable[[str], dict[str, Any]]


def run_monitoring_check(
    dashboard_data: dict[str, Any],
    *,
    storage_dir: Path = STORAGE_DIR,
    send_alert: AlertSender | None = None,
) -> dict[str, Any]:
    snapshots = build_monitoring_snapshots(dashboard_data)
    findings = []
    for snapshot in snapshots:
        findings.extend(evaluate_monitoring_snapshot(snapshot))

    alerts = [finding for finding in findings if finding.get("severity") != "info"]
    opportunities = [finding for finding in findings if finding.get("severity") == "info"]
    saved_alerts = save_monitoring_alerts(alerts, storage_dir=storage_dir)
    notifications = []
    if send_alert:
        for alert in saved_alerts:
            if alert.get("severity") in {"medium", "high"}:
                notifications.append(send_alert(format_monitoring_alert(alert)))

    return {
        "ok": True,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "snapshotsChecked": len(snapshots),
        "alerts": saved_alerts,
        "opportunities": opportunities,
        "notifications": notifications,
    }


def build_monitoring_snapshots(dashboard_data: dict[str, Any]) -> list[dict[str, Any]]:
    campaign_names = {str(campaign.get("id")): campaign.get("name") for campaign in dashboard_data.get("campaigns", [])}
    eligible_campaign_ids = {
        str(campaign.get("id"))
        for campaign in dashboard_data.get("campaigns", [])
        if str(campaign.get("status", "active")).lower() in {"active", "paused"}
    }
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    latest_metric_date = latest_date(dashboard_data.get("metrics", []))
    stale_before = latest_metric_date - timedelta(days=7) if latest_metric_date else None
    for row in dashboard_data.get("metrics", []):
        campaign_id = str(row.get("campaignId") or row.get("campaign_id") or "")
        date = str(row.get("date") or row.get("date_start") or "")
        if not campaign_id or not date:
            continue
        if eligible_campaign_ids and campaign_id not in eligible_campaign_ids:
            continue
        grouped.setdefault(campaign_id, {}).setdefault(date, []).append(row)

    snapshots = []
    for campaign_id, by_date in grouped.items():
        dates = sorted(by_date)
        if len(dates) < 2:
            continue
        if stale_before and parse_date(dates[-1]) < stale_before:
            continue
        previous_date, current_date = dates[-2], dates[-1]
        snapshots.append(
            {
                "campaignId": campaign_id,
                "campaignName": campaign_names.get(campaign_id) or campaign_id,
                "previous": aggregate_rows(by_date[previous_date]),
                "current": aggregate_rows(by_date[current_date]),
                "previousDate": previous_date,
                "currentDate": current_date,
            }
        )
    return snapshots


def latest_date(rows: list[dict[str, Any]]) -> datetime | None:
    dates = [parse_date(str(row.get("date") or row.get("date_start") or "")) for row in rows]
    dates = [date for date in dates if date != datetime.min]
    return max(dates) if dates else None


def parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError:
        return datetime.min


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "spend": sum(number(row.get("spendUsd", row.get("spend", 0))) for row in rows),
        "clicks": sum(number(row.get("clicks", 0)) for row in rows),
        "leads": sum(number(row.get("leads", 0)) for row in rows),
        "telegramStarts": sum(number(row.get("telegramSubscribers", row.get("telegramStarts", 0))) for row in rows),
    }


def save_monitoring_alerts(alerts: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    if not alerts:
        return []
    existing = list_monitoring_alerts(storage_dir=storage_dir)
    existing_ids = {alert.get("id") for alert in existing}
    new_alerts = [alert for alert in alerts if alert.get("id") not in existing_ids]
    rows = [*new_alerts, *existing]
    write_monitoring_alerts(rows, storage_dir=storage_dir)
    return new_alerts


def list_monitoring_alerts(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    payload = read_json(storage_dir / "monitoring_alerts.json", [])
    return payload if isinstance(payload, list) else []


def write_monitoring_alerts(rows: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> None:
    write_json_atomic(storage_dir / "monitoring_alerts.json", rows)


def format_monitoring_alert(alert: dict[str, Any]) -> str:
    actions = "\n".join(f"- {action}" for action in alert.get("recommendedActions", [])[:3])
    return "\n".join(
        [
            "Meta Agent monitoring alert",
            f"Severity: {alert.get('severity', 'unknown')}",
            f"Campaign: {alert.get('campaignName') or alert.get('campaignId') or 'unknown'}",
            f"Issue: {alert.get('title')}",
            "",
            "Recommended next actions:",
            actions or "- Review campaign before changing budget.",
        ]
    )


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0

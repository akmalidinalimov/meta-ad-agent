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
ROOT = Path(__file__).resolve().parents[1]          # match targets_store.py / monitoring_scheduler.py
STORAGE_DIR = ROOT / "storage"
RUN_FILE = "daily_analysis_run.json"
TZ = ZoneInfo("Europe/Stockholm")
SEND_HOUR = 18


def should_run_daily(now: datetime, *, last_run_date: str | None) -> bool:
    """Return True only when the clock is at or past SEND_HOUR and we haven't run today."""
    local = now.astimezone(TZ)
    if local.hour < SEND_HOUR:
        return False
    return last_run_date != local.date().isoformat()


def _last_run_date(*, storage_dir: Path = STORAGE_DIR) -> str | None:
    payload = read_json(storage_dir / RUN_FILE, None)
    return payload.get("date") if isinstance(payload, dict) else None


def run_scheduled_daily_analysis(*, force: bool = False, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Run + send the daily analysis if the gate is open (or forced). Returns a status dict.

    Sync (uses asyncio.run) so it can be called via asyncio.to_thread from the async loop;
    callers already inside an event loop MUST use asyncio.to_thread, not call this directly.
    """
    from .daily_analyst import run_daily_analysis
    from .telegram_digest import build_daily_analyst_message
    from .telegram_outbound import send_telegram_message_sync

    now = datetime.now(TZ)
    if not force and not should_run_daily(now, last_run_date=_last_run_date(storage_dir=storage_dir)):
        return {"skipped": True, "reason": "Outside the 18:00 window or already ran today."}

    analysis = asyncio.run(run_daily_analysis())
    message = build_daily_analyst_message(analysis)
    try:
        send_telegram_message_sync(message)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send daily analyst report")
    write_json_atomic(storage_dir / RUN_FILE, {"date": now.date().isoformat(), "ok": analysis.get("ok")})
    return {"skipped": False, "ok": analysis.get("ok"), "sent": True}


ANOMALY_RUN_FILE = "intraday_anomaly_run.json"


def run_intraday_anomaly_check(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Run the account-level anomaly check and Telegram-alert only on NEW anomaly kinds,
    debounced per Stockholm day so a persistent condition doesn't ping every 4h. Sync (uses
    asyncio.run); call via asyncio.to_thread from the async loop."""
    from .daily_analyst import intraday_anomaly_alerts
    from .telegram_outbound import send_telegram_message_sync

    alerts = asyncio.run(intraday_anomaly_alerts())
    today = datetime.now(TZ).date().isoformat()
    payload = read_json(storage_dir / ANOMALY_RUN_FILE, None)
    already = set(payload.get("kinds", [])) if isinstance(payload, dict) and payload.get("date") == today else set()
    fresh = [a for a in alerts if a["kind"] not in already]
    if fresh:
        message = "⚠️ Intra-day alert:\n" + "\n".join(f"• {a['message']}" for a in fresh)
        try:
            send_telegram_message_sync(message)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send intra-day anomaly alert")
        write_json_atomic(storage_dir / ANOMALY_RUN_FILE,
                          {"date": today, "kinds": sorted(already | {a["kind"] for a in fresh})})
    return {"alerts": len(alerts), "new": len(fresh)}

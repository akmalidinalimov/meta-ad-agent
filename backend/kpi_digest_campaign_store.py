"""Globally-selected campaign for the recurring KPI digest.

The 4-hourly KPI digest defaults to an account-wide summary, which left the operator
unsure which campaign the numbers referred to. The operator can now pin ONE campaign
(via the Telegram KPI panel) so each digest reports just that campaign; resetting
clears the pin and returns to the account-wide view.

Scope is global on purpose: the digest has a single destination (the admin chat), so a
single selection is all that's needed. Persisted as a small JSON file alongside the
other file-based stores so the pin survives restarts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
KPI_DIGEST_CAMPAIGN_FILE = "kpi_digest_campaign.json"


def load_kpi_digest_campaign(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any] | None:
    """The pinned campaign, or None when the digest is account-wide (no pin / reset)."""
    payload = read_json(storage_dir / KPI_DIGEST_CAMPAIGN_FILE, None)
    if isinstance(payload, dict) and payload.get("campaignId"):
        return {
            "campaignId": str(payload.get("campaignId")),
            "campaignName": str(payload.get("campaignName") or ""),
            "selectedAt": payload.get("selectedAt"),
            "selectedBy": payload.get("selectedBy"),
        }
    return None


def set_kpi_digest_campaign(
    campaign_id: str,
    campaign_name: str = "",
    *,
    selected_by: str | None = None,
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    record = {
        "campaignId": str(campaign_id),
        "campaignName": str(campaign_name or ""),
        "selectedAt": datetime.now(timezone.utc).isoformat(),
        "selectedBy": str(selected_by) if selected_by is not None else None,
    }
    write_json_atomic(storage_dir / KPI_DIGEST_CAMPAIGN_FILE, record)
    return record


def clear_kpi_digest_campaign(*, storage_dir: Path = STORAGE_DIR) -> None:
    """Reset to the account-wide digest. Keeps the file (empty object), not deleted."""
    write_json_atomic(storage_dir / KPI_DIGEST_CAMPAIGN_FILE, {})

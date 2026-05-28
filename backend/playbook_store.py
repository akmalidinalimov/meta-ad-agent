from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
PLAYBOOKS_PATH = STORAGE_DIR / "campaign_playbooks.json"


def default_playbook() -> dict[str, Any]:
    return {
        "id": "pb_default",
        "name": "Configurable AI course launch",
        "goal": "Find the best quality audience and creative mix for paid AI course sales.",
        "primarySuccessMetric": "telegram_start",
        "secondarySuccessMetrics": ["crm_form_submit", "qualified_lead", "purchase"],
        "segments": [],
        "rules": {
            "startingBudgetUsd": 100,
            "maxDailyBudgetUsd": 500,
            "scalingStepPercent": 20,
            "scalingFrequencyDays": 1,
            "salesCapacityLeadsPerDay": 200,
            "requiresApprovalForExecution": True,
        },
        "alertChannels": ["dashboard"],
        "approvalChannels": ["dashboard"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def load_playbooks(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "campaign_playbooks.json"
    if not path.exists():
        return [default_playbook()]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [default_playbook()]
    if isinstance(payload, list) and payload:
        return payload
    return [default_playbook()]


def save_playbook(playbook: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    playbooks = [item for item in load_playbooks(storage_dir=storage_dir) if item.get("id") != playbook.get("id")]
    now = datetime.now(timezone.utc).isoformat()
    next_playbook = {
        **playbook,
        "id": playbook.get("id") or f"pb_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "updatedAt": now,
    }
    next_playbook.setdefault("createdAt", now)
    playbooks.insert(0, next_playbook)
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "campaign_playbooks.json").write_text(
        json.dumps(playbooks, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return next_playbook

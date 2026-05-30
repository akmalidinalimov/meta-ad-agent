from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"


def list_crm_leads(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "crm_leads.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def save_crm_leads(leads: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    existing = list_crm_leads(storage_dir=storage_dir)
    by_key = {lead_key(lead): lead for lead in existing}
    now = datetime.now(timezone.utc).isoformat()
    saved = []
    for lead in leads:
        key = lead_key(lead)
        merged = {
            **by_key.get(key, {}),
            **lead,
            "importedAt": now,
        }
        by_key[key] = merged
        saved.append(merged)
    rows = list(by_key.values())
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "crm_leads.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return saved


def lead_key(lead: dict[str, Any]) -> str:
    return f"{lead.get('crm', 'crm')}:{lead.get('crmLeadId') or lead.get('id') or lead.get('visitorId')}"

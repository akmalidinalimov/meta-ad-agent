from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
KNOWLEDGE_BASE_PATH = STORAGE_DIR / "meta_knowledge_base.json"


def save_knowledge_base(payload: dict[str, Any]) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    payload["savedAt"] = datetime.now(timezone.utc).isoformat()
    KNOWLEDGE_BASE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_knowledge_base() -> dict[str, Any] | None:
    if not KNOWLEDGE_BASE_PATH.exists():
        return None
    return json.loads(KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8"))

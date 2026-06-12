from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
KNOWLEDGE_BASE_PATH = STORAGE_DIR / "meta_knowledge_base.json"


def save_knowledge_base(payload: dict[str, Any]) -> None:
    payload["savedAt"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(KNOWLEDGE_BASE_PATH, payload)


def load_knowledge_base() -> dict[str, Any] | None:
    return read_json(KNOWLEDGE_BASE_PATH, None)

"""Persistence for captured Meta Ads Manager AI ("Analyze") output.

Captures are stored append-only in storage/meta_ai_captures.json. Each capture
keeps the raw pasted text/screenshot text plus the Advisor/Strategist analysis
computed at save time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage_io import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
CAPTURES_FILE = "meta_ai_captures.json"


def list_captures(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    payload = read_json(storage_dir / CAPTURES_FILE, [])
    rows = payload if isinstance(payload, list) else []
    # Most recent first.
    return sorted(rows, key=lambda row: row.get("createdAt", ""), reverse=True)


def save_capture(capture: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    existing = list_captures(storage_dir=storage_dir)
    existing = [row for row in existing if row.get("id") != capture.get("id")]
    existing.append(capture)
    write_json_atomic(storage_dir / CAPTURES_FILE, existing)
    return capture

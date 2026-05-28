from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
SNAPSHOT_DIR = STORAGE_DIR / "snapshots"


def build_snapshot_payload(
    *,
    raw: dict[str, Any],
    analysis: dict[str, Any],
    account_id: str,
    days: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    safe_account_id = account_id or "unknown_account"
    snapshot_id = f"meta-{safe_account_id}-{timestamp}-{days}d"

    return {
        "id": snapshot_id,
        "kind": "meta",
        "accountId": safe_account_id,
        "days": days,
        "generatedAt": generated_at.isoformat(),
        "rawCounts": analysis.get("rawCounts", {}),
        "summary": analysis.get("summary", {}),
        "raw": raw,
        "analysis": analysis,
    }


def save_snapshot(payload: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    snapshot_dir = storage_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{payload['id']}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot_metadata(payload)


def list_snapshots(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    snapshot_dir = storage_dir / "snapshots"
    if not snapshot_dir.exists():
        return []

    snapshots = []
    for path in snapshot_dir.glob("*.json"):
        try:
            snapshots.append(snapshot_metadata(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return sorted(snapshots, key=lambda item: item.get("generatedAt", ""), reverse=True)


def latest_snapshot(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any] | None:
    snapshots = list_snapshots(storage_dir=storage_dir)
    if not snapshots:
        return None
    return load_snapshot(snapshots[0]["id"], storage_dir=storage_dir)


def load_snapshot(snapshot_id: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any] | None:
    path = storage_dir / "snapshots" / f"{snapshot_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": payload["id"],
        "kind": payload.get("kind", "meta"),
        "accountId": payload.get("accountId", ""),
        "days": payload.get("days", 0),
        "generatedAt": payload.get("generatedAt"),
        "rawCounts": payload.get("rawCounts", {}),
        "summary": payload.get("summary", {}),
    }

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
APPROVALS_PATH = STORAGE_DIR / "approval_requests.json"


def list_approval_requests(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "approval_requests.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def create_approval_request(request: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    rows = [row for row in list_approval_requests(storage_dir=storage_dir) if row.get("id") != request.get("id")]
    now = datetime.now(timezone.utc).isoformat()
    saved = {
        **request,
        "id": request.get("id") or f"approval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "createdAt": request.get("createdAt") or now,
        "updatedAt": now,
    }
    rows.insert(0, saved)
    write_approval_requests(rows, storage_dir=storage_dir)
    return saved


def approve_request(
    approval_id: str,
    *,
    approved_by: str,
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    rows = list_approval_requests(storage_dir=storage_dir)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("id") == approval_id:
            if row.get("status") == "blocked":
                raise ValueError("Blocked approval requests cannot be approved.")
            row["status"] = "approved"
            row["approvedBy"] = approved_by
            row["approvedAt"] = now
            row["updatedAt"] = now
            write_approval_requests(rows, storage_dir=storage_dir)
            return row
    raise KeyError(f"Approval request not found: {approval_id}")


def reject_request(
    approval_id: str,
    *,
    rejected_by: str,
    reason: str = "",
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    rows = list_approval_requests(storage_dir=storage_dir)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("id") == approval_id:
            row["status"] = "rejected"
            row["rejectedBy"] = rejected_by
            row["rejectionReason"] = reason
            row["rejectedAt"] = now
            row["updatedAt"] = now
            write_approval_requests(rows, storage_dir=storage_dir)
            return row
    raise KeyError(f"Approval request not found: {approval_id}")


def request_changes(
    approval_id: str,
    *,
    requested_by: str,
    note: str = "",
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    rows = list_approval_requests(storage_dir=storage_dir)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("id") == approval_id:
            row["status"] = "needs_changes"
            row["changesRequestedBy"] = requested_by
            row["changeRequestNote"] = note
            row["changesRequestedAt"] = now
            row["updatedAt"] = now
            write_approval_requests(rows, storage_dir=storage_dir)
            return row
    raise KeyError(f"Approval request not found: {approval_id}")


def update_approval_request(
    approval_id: str,
    patch: dict[str, Any],
    *,
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    rows = list_approval_requests(storage_dir=storage_dir)
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        if row.get("id") == approval_id:
            row.update(patch)
            row["updatedAt"] = now
            write_approval_requests(rows, storage_dir=storage_dir)
            return row
    raise KeyError(f"Approval request not found: {approval_id}")


def write_approval_requests(rows: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "approval_requests.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

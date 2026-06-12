from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, update_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
APPROVALS_PATH = STORAGE_DIR / "approval_requests.json"


def _path(storage_dir: Path) -> Path:
    return storage_dir / "approval_requests.json"


def list_approval_requests(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    payload = read_json(_path(storage_dir), [])
    return payload if isinstance(payload, list) else []


def create_approval_request(request: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    saved = {
        **request,
        "id": request.get("id") or f"approval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "createdAt": request.get("createdAt") or now,
        "updatedAt": now,
    }

    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rows[:] = [row for row in rows if row.get("id") != saved["id"]]
        rows.insert(0, saved)
        return saved

    return update_json(_path(storage_dir), mutate, default=[])


def _mutate_row(approval_id: str, storage_dir: Path, apply: Any) -> dict[str, Any]:
    def mutate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        for row in rows:
            if row.get("id") == approval_id:
                apply(row)
                row["updatedAt"] = datetime.now(timezone.utc).isoformat()
                return row
        raise KeyError(f"Approval request not found: {approval_id}")

    return update_json(_path(storage_dir), mutate, default=[])


def approve_request(approval_id: str, *, approved_by: str, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    def apply(row: dict[str, Any]) -> None:
        if row.get("status") == "blocked":
            raise ValueError("Blocked approval requests cannot be approved.")
        row["status"] = "approved"
        row["approvedBy"] = approved_by
        row["approvedAt"] = datetime.now(timezone.utc).isoformat()

    return _mutate_row(approval_id, storage_dir, apply)


def reject_request(approval_id: str, *, rejected_by: str, reason: str = "", storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    def apply(row: dict[str, Any]) -> None:
        row["status"] = "rejected"
        row["rejectedBy"] = rejected_by
        row["rejectionReason"] = reason
        row["rejectedAt"] = datetime.now(timezone.utc).isoformat()

    return _mutate_row(approval_id, storage_dir, apply)


def request_changes(approval_id: str, *, requested_by: str, note: str = "", storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    def apply(row: dict[str, Any]) -> None:
        row["status"] = "needs_changes"
        row["changesRequestedBy"] = requested_by
        row["changeRequestNote"] = note
        row["changesRequestedAt"] = datetime.now(timezone.utc).isoformat()

    return _mutate_row(approval_id, storage_dir, apply)


def update_approval_request(approval_id: str, patch: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    return _mutate_row(approval_id, storage_dir, lambda row: row.update(patch))


def write_approval_requests(rows: list[dict[str, Any]], *, storage_dir: Path = STORAGE_DIR) -> None:
    write_json_atomic(_path(storage_dir), rows)

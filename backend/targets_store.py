"""Operator-set KPI targets (goals).

Account-level performance goals the operator wants the agent to steer toward and
report against. The 4-hourly KPI digest annotates each KPI with a ✅/⚠️ marker vs
these targets, so a breach is surfaced proactively every cycle. Stored as a small
JSON file alongside the other file-based stores. All fields are optional (null =
no target set for that KPI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage_io import read_json, write_json_atomic

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
TARGETS_FILE = "kpi_targets.json"

# Each target is (key, direction): "max" = actual should stay AT OR BELOW the target
# (cost-type KPIs); "min" = actual should stay AT OR ABOVE the target (rate-type KPIs).
TARGET_FIELDS: dict[str, str] = {
    "maxCpl": "max",            # $ ceiling for cost per lead
    "minLeadRate": "min",       # % floor for lead rate (leads / clicks)
    "maxCostPerStart": "max",   # $ ceiling for cost per Telegram START
    "minStartRate": "min",      # % floor for Telegram START rate
}


def default_targets() -> dict[str, Any]:
    return {key: None for key in TARGET_FIELDS}


def load_targets(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    payload = read_json(storage_dir / TARGETS_FILE, None)
    targets = default_targets()
    if isinstance(payload, dict):
        for key in TARGET_FIELDS:
            value = payload.get(key)
            targets[key] = _coerce(value)
    return targets


def save_targets(patch: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    targets = load_targets(storage_dir=storage_dir)
    for key in TARGET_FIELDS:
        if key in patch:
            targets[key] = _coerce(patch[key])
    write_json_atomic(storage_dir / TARGETS_FILE, targets)
    return targets


def _coerce(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def has_any_target(targets: dict[str, Any]) -> bool:
    return any(value is not None for value in targets.values())

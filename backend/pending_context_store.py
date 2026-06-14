"""Pending-context store for autonomous campaign refinement (Theme A core).

When the orchestrator autonomously builds a best-guess PAUSED campaign, it records a
small *pointer* keyed by the operator (Telegram chat or web session). A later operator
message ("make it $50", "Tashkent only") can then be merged onto that pointer to refine
the in-flight suggestion instead of starting over.

This module is the storage + merge helper ONLY. Wiring it into the routers (Telegram /
web chat) is a separate later workstream — nothing here is imported by a router yet.

Storage mirrors approval_store: one JSON file (``storage/pending_context.json``) mapping
``operator_key -> pointer``, written through the same lock-guarded ``storage_io`` helpers
so concurrent writes serialize and never lose an update.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chat_campaign_planner import (
    extract_budget,
    extract_locations,
    extract_segment_names,
    extract_success_metric,
)
from .storage_io import read_json, update_json

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
PENDING_FILENAME = "pending_context.json"


def _path(storage_dir: Path) -> Path:
    return storage_dir / PENDING_FILENAME


def operator_key(*, telegram_chat_id: Any = None, session_id: str | None = None) -> str:
    """Stable key identifying the operator a pending context belongs to.

    Telegram chat id wins (the cross-device identity); a web session id is next; and a
    shared ``web:default`` is the fallback for an unauthenticated single-operator web UI.
    """
    if telegram_chat_id is not None and str(telegram_chat_id).strip():
        return f"tg:{str(telegram_chat_id).strip()}"
    if session_id is not None and str(session_id).strip():
        return f"web:{str(session_id).strip()}"
    return "web:default"


def _read_all(storage_dir: Path) -> dict[str, Any]:
    payload = read_json(_path(storage_dir), {})
    return payload if isinstance(payload, dict) else {}


def get_pending(operator_key: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any] | None:
    """Return the operator's pending pointer, or ``None`` when nothing is stored."""
    pointer = _read_all(storage_dir).get(operator_key)
    return pointer if isinstance(pointer, dict) else None


def set_pending(operator_key: str, pointer: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Store (replace) the operator's pending pointer and return what was saved.

    A ``createdAt`` is stamped when the pointer doesn't already carry one, so callers
    can store a bare ``{"approvalId": ...}`` and still get a timestamp.
    """
    saved = {
        "approvalId": pointer.get("approvalId"),
        "openQuestions": pointer.get("openQuestions") or [],
        "budget": pointer.get("budget"),
        "audiences": pointer.get("audiences") or [],
        "createdAt": pointer.get("createdAt") or datetime.now(timezone.utc).isoformat(),
    }
    # Bulk-manage pointers carry a kind/action so a typed "approve" can resolve the right
    # approval; only persisted when present so autonomous pointers stay unchanged.
    if pointer.get("kind"):
        saved["kind"] = pointer["kind"]
    if pointer.get("action"):
        saved["action"] = pointer["action"]
    if pointer.get("label") is not None:
        saved["label"] = pointer["label"]
    if pointer.get("guided") is not None:
        saved["guided"] = pointer["guided"]

    def mutate(rows: dict[str, Any]) -> dict[str, Any]:
        rows[operator_key] = saved
        return saved

    return update_json(_path(storage_dir), mutate, default={})


def clear_pending(operator_key: str, *, storage_dir: Path = STORAGE_DIR) -> None:
    """Drop the operator's pending pointer (no-op when nothing is stored)."""

    def mutate(rows: dict[str, Any]) -> None:
        rows.pop(operator_key, None)
        return None

    update_json(_path(storage_dir), mutate, default={})


def merge_refinement(pointer: dict[str, Any], message: str, knowledge: dict[str, Any] | None) -> dict[str, Any]:
    """Return only the non-None overrides extracted from a refinement ``message``.

    Reuses the chat_campaign_planner extractors so refinement parsing matches the
    initial-brief parsing exactly. Keys are only present when the message actually
    carries that signal, so the caller can ``{**existing, **overrides}`` safely.
    """
    overrides: dict[str, Any] = {}

    budget = extract_budget(message)
    if budget is not None:
        overrides["budget"] = budget

    locations = extract_locations(message)
    # extract_locations defaults to ["Uzbekistan"]; treat that bare default as "no
    # explicit location given" so we don't clobber a more specific existing value.
    lower = message.lower()
    if locations and locations != ["Uzbekistan"]:
        overrides["locations"] = locations
    elif "uzbekistan" in lower or "broad" in lower:
        overrides["locations"] = ["Uzbekistan"]

    segments = extract_segment_names(message)
    if segments:
        overrides["audiences"] = segments

    metric = extract_success_metric(message)
    # extract_success_metric always returns a value (defaulting to bot_start); only treat
    # it as an explicit override when the message names a metric-bearing signal.
    if any(token in lower for token in ["qualified lead", "full payment", "purchase", "paid course", "form", "telegram", "start"]):
        overrides["successMetric"] = metric

    return overrides

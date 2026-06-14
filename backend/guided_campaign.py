"""Guided PAUSED-campaign creation: a small state machine over the Telegram
pending-context store. Steps: audience -> creatives -> propose. Transport
(send/edit) and Meta builders live elsewhere; this module only decides the next
message + buttons and advances the stored step."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pending_context_store import STORAGE_DIR, get_pending, set_pending

GUIDED_KIND = "guided_create"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guided(operator_key: str, storage_dir: Path) -> dict[str, Any] | None:
    p = get_pending(operator_key, storage_dir=storage_dir)
    if p and p.get("kind") == GUIDED_KIND:
        return p.get("guided") or {}
    return None


def _save(operator_key: str, guided: dict[str, Any], storage_dir: Path) -> None:
    set_pending(operator_key, {"kind": GUIDED_KIND, "guided": guided}, storage_dir=storage_dir)


def start(operator_key: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    _save(operator_key, {"step": "audience", "selectedCreatives": [], "startedAt": _now_iso()}, storage_dir)
    return {
        "text": "Let's build a PAUSED test campaign. How should I pick the <b>audience</b>?",
        "reply_markup": {"inline_keyboard": [
            [{"text": "🏆 Proven audiences", "callback_data": "gcreate:aud:proven"}],
            [{"text": "✨ Suggest new ones", "callback_data": "gcreate:aud:new"}],
            [{"text": "✍️ I'll specify", "callback_data": "gcreate:aud:input"}],
        ]},
    }


def handle_audience_choice(operator_key: str, choice: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    guided = _guided(operator_key, storage_dir)
    if guided is None:
        return {"text": "That setup expired. Say \"create a campaign\" to start over.", "expired": True}
    if choice == "input":
        guided["step"] = "audience_text"
        _save(operator_key, guided, storage_dir)
        return {"text": "Tell me the audience — interests, age, location (e.g. \"business owners, 25-34, Tashkent\")."}
    if choice in ("proven", "new"):
        guided["step"] = "creatives"
        guided["audienceChoice"] = choice
        _save(operator_key, guided, storage_dir)
        return {"next": "render_creatives", "text": "Great — now pick the creatives."}
    return {"text": "Unknown choice."}

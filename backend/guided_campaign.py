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


def top_creatives_for_selection(knowledge: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    """The account's top creatives offered for selection. The id is the CREATIVE
    id (creative.id) — the same key build_campaign_creation_approval filters its
    ad pool on — so a selected id always maps to a real creative that becomes an
    ad. Reads the same topAds source the builder draws from."""
    analysis = (knowledge or {}).get("analysis", {}) or {}
    rows: list[dict[str, Any]] = []
    for ad in (analysis.get("topAds") or [])[: max(0, limit)]:
        if not isinstance(ad, dict):
            continue
        creative = ad.get("creative") or {}
        cid = str(creative.get("id") or "")
        if not cid:
            continue
        rows.append({
            "id": cid,
            "name": ad.get("name") or creative.get("name") or "Creative",
            "thumb": creative.get("image_url") or creative.get("thumbnail_url"),
            "videoId": creative.get("video_id"),
            "qualityScore": ad.get("qualityScore", 0),
        })
    return rows


def handle_creative_toggle(operator_key: str, creative_id: str, *, storage_dir: Path = STORAGE_DIR) -> list[str]:
    guided = _guided(operator_key, storage_dir)
    if guided is None:
        return []
    selected = list(guided.get("selectedCreatives") or [])
    if creative_id in selected:
        selected.remove(creative_id)
    else:
        selected.append(creative_id)
    guided["selectedCreatives"] = selected
    _save(operator_key, guided, storage_dir)
    return selected


def creative_toggle_label(creative_id: str, selected: list[str]) -> str:
    return "✅ Selected" if creative_id in selected else "➕ Select"

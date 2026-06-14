"""Guided PAUSED-campaign creation: a small state machine over the Telegram
pending-context store. Steps: audience -> creatives -> propose. Transport
(send/edit) and Meta builders live elsewhere; this module only decides the next
message + buttons and advances the stored step."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .opportunity_finder import build_autonomous_campaign  # module-level so tests can monkeypatch
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


# Known Uzbek cities — tokens that should be read as LOCATIONS rather than interests.
_UZ_CITIES = {
    "tashkent", "samarkand", "bukhara", "andijan", "namangan", "fergana",
    "nukus", "qarshi", "karshi", "kokand", "margilan", "jizzakh", "navoi",
    "termez", "urgench", "gulistan", "uzbekistan",
}


def _parse_audience_text(text: str) -> dict[str, Any]:
    """Deterministic (no-LLM) parse of a free-text audience description into a
    targeting spec the builder understands. Returns a dict keyed by ``label``
    (the builder reads ``label``, not ``name``) plus interests / ageRange /
    locations / gender."""
    raw = (text or "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()]

    age_range: str | None = None
    locations: list[str] = []
    interests: list[str] = []
    for token in tokens:
        age_match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})", token)
        # Pure age token (e.g. "25-34") -> ageRange; don't also treat it as an interest.
        if age_match and re.fullmatch(r"\d{1,2}\s*-\s*\d{1,2}", token):
            age_range = f"{age_match.group(1)}-{age_match.group(2)}"
            continue
        if token.lower() in _UZ_CITIES:
            locations.append(token)
            continue
        interests.append(token)

    label = raw or (interests[0] if interests else "Custom audience")
    return {
        "label": label,
        "interests": interests,
        "ageRange": age_range,
        "locations": locations,
        "gender": "all",
    }


def handle_audience_text(operator_key: str, text: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Consume the operator's free-text audience answer (the ``audience_text``
    step), store the parsed spec, advance to the creatives step, and signal the
    transport to render the creative picker."""
    guided = _guided(operator_key, storage_dir)
    if guided is None:
        return {"text": "That setup expired. Say \"create a campaign\" to start over.", "expired": True}
    spec = _parse_audience_text(text)
    guided["audienceSpec"] = [spec]
    guided["audienceChoice"] = "input"
    guided["step"] = "creatives"
    _save(operator_key, guided, storage_dir)
    return {
        "text": f"Got it — targeting: <b>{spec['label']}</b>. Now pick the creatives.",
        "next": "render_creatives",
    }


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


# ---------------------------------------------------------------------------
# Seams — monkeypatchable in tests; do lazy imports to avoid side-effects at
# module import time.
# ---------------------------------------------------------------------------


def _load_knowledge() -> dict[str, Any]:
    from .knowledge_base import load_knowledge_base
    return load_knowledge_base()


def _load_playbooks() -> list[dict[str, Any]]:
    from .playbook_store import load_playbooks
    return load_playbooks()


def _account_and_pixel() -> tuple[str | None, str | None]:
    from .meta_client import get_meta_config
    c = get_meta_config()
    return (c.ad_account_id or None), (c.pixel_id or None)


def _create_approval(approval: dict[str, Any]) -> dict[str, Any]:
    from .approval_store import create_approval_request
    return create_approval_request(approval)


# ---------------------------------------------------------------------------
# finalize — build approval + hand off to the existing agap approve path
# ---------------------------------------------------------------------------


def finalize(operator_key: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    """Build the campaign approval from the guided state and store a pending
    pointer so the existing ``agap:approve`` / ``agap:reject`` callback path
    in routers/telegram.py can execute it via ``execute_pending``."""
    guided = _guided(operator_key, storage_dir)
    if guided is None:
        return {"text": "That setup expired. Say \"create a campaign\" to start over.", "expired": True}

    choice = guided.get("audienceChoice")
    account_id, pixel_id = _account_and_pixel()
    approval = build_autonomous_campaign(
        _load_knowledge(),
        _load_playbooks(),
        account_id=account_id,
        n_audiences=3,
        n_creatives=5,
        pixel_id=pixel_id,
        audience_override=guided.get("audienceSpec"),
        creative_ids=list(guided.get("selectedCreatives") or []) or None,
        exclude_recent=(choice != "proven"),
    )
    if approval is None:
        return {"text": "I couldn't find usable audience data yet — try the autonomous build later."}

    saved = _create_approval(approval)
    after = saved.get("after") or {}
    name = after.get("name") or (after.get("campaign") or {}).get("name") or saved.get("title") or "Test campaign"
    set_pending(
        operator_key,
        {"kind": "agentic", "action": "create", "approvalId": saved["id"], "label": name},
        storage_dir=storage_dir,
    )
    adsets = after.get("adsets") or []
    audiences = ", ".join(
        str(a.get("name", "")).replace(" - DRAFT", "") for a in adsets if a.get("name")
    )
    total = sum((float(a.get("daily_budget") or 0) / 100) for a in adsets)
    return {
        "text": (
            f"Here's the proposed PAUSED campaign — <b>{name}</b>\n"
            f"Audiences: {audiences or 'top picks'}\nBudget: ${total:,.0f}/day total\n\n"
            "Nothing is created until you approve."
        ),
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": "agap:approve"},
            {"text": "✖️ Reject", "callback_data": "agap:reject"},
        ]]},
    }

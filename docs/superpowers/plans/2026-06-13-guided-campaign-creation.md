# Guided Campaign Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the one-shot "create a PAUSED test campaign" Telegram action into a guided flow that asks the operator to choose the audience (proven / new / free-text) and select creatives (top performers, shown as thumbnail/video with tap-to-toggle), then builds the campaign honoring those choices.

**Architecture:** A new `backend/guided_campaign.py` state machine drives a multi-step Telegram conversation, carrying state in the existing `pending_context_store`. It reuses the audience ranker, creative pool, media renderer, and proposal builder; the only builder changes are two optional override params threaded through `build_autonomous_campaign` → `build_campaign_creation_approval` so the operator's audience + creative picks drive the actual PAUSED ads. The final proposal reuses the existing `agap:approve` path (fixed in the prior commit).

**Tech Stack:** Python 3.11 / FastAPI; pytest. No frontend.

**Spec:** `docs/superpowers/specs/2026-06-13-guided-campaign-creation-design.md`
**Branch:** `feat/telegram-guided-campaign` (already carries the RBAC callback fix).

**Test command (CI parity):** `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q` (baseline **540 passed**). Single file: same prefix + `python -m pytest backend/test_<x>.py -v`.

---

## File structure

**Create:**
- `backend/guided_campaign.py` — flow state machine + step handlers (one responsibility: orchestrate the guided creation conversation; no transport/Meta-API code of its own).
- `backend/test_guided_campaign.py` — unit tests for the state machine.
- `backend/test_guided_campaign_api.py` — integration tests through `/api/telegram/command`.

**Modify:**
- `backend/meta_execution.py` — `build_campaign_creation_approval` gains `creative_ids` filter.
- `backend/opportunity_finder.py` — `build_autonomous_campaign` gains `audience_override`, `creative_ids`, `exclude_recent`.
- `backend/agentic_chat.py` — `create_test_campaign` tool gains `autonomous`; `_create_test_campaign` branches to the guided flow.
- `backend/routers/telegram.py` — dispatch `gcreate:*` callbacks + route the audience-text turn to the flow.

---

### Task 1: Thread operator overrides through the builders

**Files:**
- Modify: `backend/meta_execution.py:9-30` (`build_campaign_creation_approval`)
- Modify: `backend/opportunity_finder.py:90-174` (`build_autonomous_campaign`)
- Test: `backend/test_guided_campaign.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_guided_campaign.py
"""Guided campaign creation — builder overrides + flow state machine."""

from backend.meta_execution import build_campaign_creation_approval


def _playbook():
    return {
        "segments": [
            {"name": "Business education", "interests": ["Business education"],
             "ageRange": "25-44", "gender": "all", "locations": ["Tashkent"], "dailyBudget": 100},
        ],
    }


def _knowledge_with_creatives():
    # extract_top_creatives reads analysis.topAds; give three with ids.
    return {
        "analysis": {
            "topAds": [
                {"id": "cr_1", "adId": "cr_1", "name": "Winner A", "qualityScore": 90, "purchases": 5},
                {"id": "cr_2", "adId": "cr_2", "name": "Winner B", "qualityScore": 80, "purchases": 3},
                {"id": "cr_3", "adId": "cr_3", "name": "Winner C", "qualityScore": 70, "purchases": 1},
            ]
        }
    }


def _ad_creative_ids(approval):
    ids = []
    for adset in (approval.get("after") or {}).get("adsets", []):
        for ad in adset.get("ads") or []:
            ids.append(str(ad.get("creativeId")))
    return ids


def test_creative_ids_filter_limits_ads_to_selection():
    approval = build_campaign_creation_approval(
        _playbook(), account_id="act_1", knowledge=_knowledge_with_creatives(),
        creatives_limit=5, creative_ids=["cr_3"],
    )
    assert _ad_creative_ids(approval) == ["cr_3"]


def test_no_creative_ids_keeps_default_top_n():
    approval = build_campaign_creation_approval(
        _playbook(), account_id="act_1", knowledge=_knowledge_with_creatives(),
        creatives_limit=2,
    )
    # Unchanged behavior: top N by the existing ranking, not filtered.
    assert _ad_creative_ids(approval) == ["cr_1", "cr_2"]
```

- [ ] **Step 2: Run to verify failure**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -v`
Expected: FAIL — `build_campaign_creation_approval() got an unexpected keyword argument 'creative_ids'`.

(Before implementing, read `extract_top_creatives` in `backend/meta_execution.py` to confirm each pool item carries an `id`/`adId` field used as `creativeId` by `build_ad_payloads`. Filter on whichever field `build_ad_payloads` reads as the creative id — match the existing key exactly.)

- [ ] **Step 3: Implement the `creative_ids` filter**

In `backend/meta_execution.py`, add the param and filter the pool:

```python
def build_campaign_creation_approval(
    playbook: dict[str, Any],
    *,
    account_id: str,
    reason: str = "Create a paused Meta campaign structure from the approved playbook.",
    knowledge: dict[str, Any] | None = None,
    pixel_id: str | None = None,
    template: dict[str, Any] | None = None,
    creatives_limit: int = 3,
    creative_ids: list[str] | None = None,
) -> dict[str, Any]:
    campaign = build_campaign_payload(playbook, template=template)
    creatives_pool = extract_top_creatives(knowledge, limit=creatives_limit)
    if creative_ids:
        wanted = {str(cid) for cid in creative_ids}
        # Preserve the operator's selection; fall back to the pool only if the
        # filter removed everything (e.g. stale ids) so we never build an
        # ad-less campaign.
        filtered = [c for c in creatives_pool if str(c.get("id") or c.get("adId")) in wanted]
        creatives_pool = filtered or creatives_pool
    segments = playbook.get("segments", [])
    adsets = []
    for index, segment in enumerate(segments):
        adset = build_adset_payload(segment, playbook, pixel_id=pixel_id, template=template)
        adset["ads"] = build_ad_payloads(segment, creatives_pool, index, limit=creatives_limit)
        adsets.append(adset)
    # ... rest unchanged ...
```

(Keep everything from `checks = guardrail_checks(...)` onward exactly as-is.)

- [ ] **Step 4: Run the creative-ids tests**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -v`
Expected: both PASS. If `_ad_creative_ids` returns `[]`, the pool item id field differs — adjust the filter's `.get("id") or .get("adId")` to the actual key and re-run.

- [ ] **Step 5: Add the audience-override test + implement in `build_autonomous_campaign`**

Append to `backend/test_guided_campaign.py`:

```python
from backend.opportunity_finder import build_autonomous_campaign


def _knowledge_full():
    return {
        "analysis": {
            "audience": {"interests": [
                {"label": "Business education", "qualityScore": 90, "telegramSubscribers": 4},
                {"label": "E-commerce", "qualityScore": 70},
            ], "ageGender": [], "regions": []},
            "topAds": _knowledge_with_creatives()["analysis"]["topAds"],
            "summary": {},
        }
    }


def test_audience_override_builds_those_audiences():
    approval = build_autonomous_campaign(
        _knowledge_full(), [], account_id="act_1", n_creatives=5,
        audience_override=[{"name": "Crypto traders", "interests": ["Crypto"],
                            "ageRange": "25-34", "gender": "all", "locations": ["Tashkent"]}],
    )
    names = [a.get("name", "") for a in (approval.get("after") or {}).get("adsets", [])]
    assert any("Crypto traders" in n for n in names)


def test_default_path_unchanged_when_no_overrides():
    approval = build_autonomous_campaign(_knowledge_full(), [], account_id="act_1", n_creatives=5)
    assert approval is not None
    assert (approval.get("after") or {}).get("adsets")
```

In `backend/opportunity_finder.py`, extend the signature and branch the audience source. Add params `audience_override: list[dict[str, Any]] | None = None`, `creative_ids: list[str] | None = None`, `exclude_recent: bool = True`. Replace the audience-selection block:

```python
    if audience_override:
        audiences = audience_override
    else:
        exclude_labels = _recent_labels(playbooks) if exclude_recent else []
        audiences = rank_audiences_for_next_campaign(
            analysis, exclude_labels=exclude_labels, n=n_audiences
        )
    if not audiences:
        return None
```

Thread `creative_ids` into the approval build:

```python
    approval = build_campaign_creation_approval(
        playbook,
        account_id=account,
        reason=(...),                      # unchanged
        knowledge=knowledge,
        pixel_id=pixel_id,
        template=template_config,
        creatives_limit=n_creatives,
        creative_ids=creative_ids,
    )
```

(`_playbook_from_audiences` already accepts a list of audience dicts with `name`/`interests`/`ageRange`/`gender`/`locations`; the override list uses that exact shape.)

- [ ] **Step 6: Run all Task-1 tests + regression**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py backend/test_opportunity_finder.py -q`
Expected: all PASS (existing opportunity_finder tests still green — defaults unchanged).

- [ ] **Step 7: Commit**

```bash
git add backend/meta_execution.py backend/opportunity_finder.py backend/test_guided_campaign.py
git commit -m "feat: thread audience + creative overrides through campaign builders"
```

---

### Task 2: Guided flow state machine (audience step)

**Files:**
- Create: `backend/guided_campaign.py`
- Test: `backend/test_guided_campaign.py` (append)

The flow stores a pending pointer via `pending_context_store.set_pending(operator_key, {...})`. Note `set_pending` only persists known keys (`approvalId`, `openQuestions`, `budget`, `audiences`, `createdAt`, `kind`, `action`) — so the guided pointer reuses these: `kind="guided_create"`, `action`=current step, `audiences`=selected-audience choice payload, `budget`=unused. Selected creative ids ride in `audiences` is wrong shape; instead store the whole guided state under `openQuestions`? No — extend `set_pending` to also persist a `guided` dict. **First task step: extend `set_pending` to persist a `guided` blob.**

- [ ] **Step 1: Extend `pending_context_store.set_pending` to carry a `guided` blob**

Add to the `saved` dict in `set_pending` (`backend/pending_context_store.py:69-82`):

```python
    if pointer.get("guided") is not None:
        saved["guided"] = pointer["guided"]
```

Add a test in `backend/test_telegram_pending.py` (or `test_guided_campaign.py`):

```python
def test_pending_persists_guided_blob(tmp_path):
    from backend.pending_context_store import set_pending, get_pending
    storage = tmp_path
    set_pending("tg:1", {"kind": "guided_create", "guided": {"step": "audience", "selectedCreatives": ["cr_1"]}}, storage_dir=storage)
    got = get_pending("tg:1", storage_dir=storage)
    assert got["kind"] == "guided_create"
    assert got["guided"]["selectedCreatives"] == ["cr_1"]
```

Run it → fail (guided dropped) → implement → pass.

- [ ] **Step 2: Write the failing state-machine tests**

Append to `backend/test_guided_campaign.py`:

```python
from backend import guided_campaign


def test_start_sets_audience_step_and_returns_question(tmp_path):
    out = guided_campaign.start("tg:1", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    p = get_pending("tg:1", storage_dir=tmp_path)
    assert p["kind"] == "guided_create"
    assert p["guided"]["step"] == "audience"
    assert "audience" in out["text"].lower()
    # Three inline choices with gcreate:aud:* callbacks.
    cbs = [b["callback_data"] for row in out["reply_markup"]["inline_keyboard"] for b in row]
    assert {"gcreate:aud:proven", "gcreate:aud:new", "gcreate:aud:input"} <= set(cbs)


def test_audience_choice_input_prompts_for_text(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    out = guided_campaign.handle_audience_choice("tg:1", "input", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    assert get_pending("tg:1", storage_dir=tmp_path)["guided"]["step"] == "audience_text"
    assert "tell me" in out["text"].lower() or "audience" in out["text"].lower()


def test_audience_choice_proven_advances_to_creatives(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    out = guided_campaign.handle_audience_choice("tg:1", "proven", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    p = get_pending("tg:1", storage_dir=tmp_path)
    assert p["guided"]["step"] == "creatives"
    assert p["guided"]["audienceChoice"] == "proven"
    assert out["next"] == "render_creatives"
```

- [ ] **Step 3: Run to verify failure**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -k audience -v`
Expected: FAIL — `No module named 'backend.guided_campaign'`.

- [ ] **Step 4: Implement the audience step**

```python
# backend/guided_campaign.py
"""Guided PAUSED-campaign creation: a small state machine over the Telegram
pending-context store. Steps: audience -> creatives -> propose. Transport
(send/edit) and Meta builders live elsewhere; this module only decides what
the next message + buttons are and advances the stored step."""

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
```

- [ ] **Step 5: Run to verify pass**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -k "audience or pending_persists" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/guided_campaign.py backend/pending_context_store.py backend/test_guided_campaign.py backend/test_telegram_pending.py
git commit -m "feat: guided campaign flow — audience step state machine"
```

---

### Task 3: Creative pool, picker render, and toggle

**Files:**
- Modify: `backend/guided_campaign.py`
- Test: `backend/test_guided_campaign.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_creative_toggle_adds_then_removes(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    guided_campaign.handle_audience_choice("tg:1", "proven", storage_dir=tmp_path)
    sel1 = guided_campaign.handle_creative_toggle("tg:1", "cr_1", storage_dir=tmp_path)
    assert sel1 == ["cr_1"]
    sel2 = guided_campaign.handle_creative_toggle("tg:1", "cr_2", storage_dir=tmp_path)
    assert set(sel2) == {"cr_1", "cr_2"}
    sel3 = guided_campaign.handle_creative_toggle("tg:1", "cr_1", storage_dir=tmp_path)
    assert sel3 == ["cr_2"]


def test_top_creatives_for_selection_shape():
    knowledge = {"analysis": {"topAds": [
        {"id": "cr_1", "name": "A", "qualityScore": 9, "creative": {"thumbnail_url": "t1", "video_id": "v1"}},
        {"id": "cr_2", "name": "B", "qualityScore": 8, "creative": {"image_url": "i2"}},
    ]}}
    rows = guided_campaign.top_creatives_for_selection(knowledge, limit=5)
    assert rows[0]["id"] == "cr_1"
    assert rows[0]["thumb"] in ("t1", None) or rows[0]["videoId"] == "v1"
    assert {"id", "name", "thumb", "videoId"} <= set(rows[0].keys())
```

- [ ] **Step 2: Run to verify failure**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -k "toggle or top_creatives" -v`
Expected: FAIL — attributes not defined.

- [ ] **Step 3: Implement pool + toggle**

Add to `backend/guided_campaign.py` (reuse the account's ranked top ads — same source `build_campaign_creation_approval` uses, so the picker shows exactly the creatives that can become ads):

```python
def top_creatives_for_selection(knowledge: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    """The account's top creatives offered for selection, newest media first.
    Mirrors the pool build_campaign_creation_approval draws ads from, so a
    selected id always maps to a real creative."""
    analysis = (knowledge or {}).get("analysis", {}) or {}
    rows: list[dict[str, Any]] = []
    for ad in (analysis.get("topAds") or [])[: max(0, limit)]:
        if not isinstance(ad, dict):
            continue
        creative = ad.get("creative") or {}
        rows.append({
            "id": str(ad.get("id") or ad.get("adId") or ""),
            "name": ad.get("name") or "Creative",
            "thumb": creative.get("image_url") or creative.get("thumbnail_url"),
            "videoId": creative.get("video_id"),
            "qualityScore": ad.get("qualityScore", 0),
        })
    return [r for r in rows if r["id"]]


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
```

- [ ] **Step 4: Run to verify pass**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -k "toggle or top_creatives" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/guided_campaign.py backend/test_guided_campaign.py
git commit -m "feat: guided campaign flow — creative pool + tap-to-toggle selection"
```

---

### Task 4: Finalize → build proposal (hands to the existing approve path)

**Files:**
- Modify: `backend/guided_campaign.py`
- Test: `backend/test_guided_campaign.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_finalize_builds_approval_with_selection(tmp_path, monkeypatch):
    import backend.guided_campaign as gc

    # Avoid real Meta/knowledge: stub the builder + approval store + meta config.
    captured = {}

    def fake_build(knowledge, playbooks, **kw):
        captured.update(kw)
        return {"id": "appr_x", "after": {"name": "VSL Test", "adsets": [
            {"name": "Business education - DRAFT", "daily_budget": 10000, "ads": [{"creativeId": "cr_1"}]}]}}

    monkeypatch.setattr(gc, "build_autonomous_campaign", fake_build, raising=False)
    monkeypatch.setattr(gc, "_load_knowledge", lambda: {"analysis": {}})
    monkeypatch.setattr(gc, "_load_playbooks", lambda: [])
    monkeypatch.setattr(gc, "_account_and_pixel", lambda: ("act_1", None))
    monkeypatch.setattr(gc, "_create_approval", lambda approval: approval)

    gc.start("tg:1", storage_dir=tmp_path)
    gc.handle_audience_choice("tg:1", "proven", storage_dir=tmp_path)
    gc.handle_creative_toggle("tg:1", "cr_1", storage_dir=tmp_path)
    out = gc.finalize("tg:1", storage_dir=tmp_path)

    # Operator selection threaded into the builder.
    assert captured.get("creative_ids") == ["cr_1"]
    assert captured.get("exclude_recent") is False  # 'proven' = include proven/recent
    # Leaves an agentic 'create' pending so the existing agap:approve path executes it.
    from backend.pending_context_store import get_pending
    p = get_pending("tg:1", storage_dir=tmp_path)
    assert p["kind"] == "agentic" and p["action"] == "create" and p["approvalId"] == "appr_x"
    assert "approve" in out["text"].lower()
    cbs = [b["callback_data"] for row in out["reply_markup"]["inline_keyboard"] for b in row]
    assert {"agap:approve", "agap:reject"} <= set(cbs)
```

- [ ] **Step 2: Run to verify failure**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -k finalize -v`
Expected: FAIL.

- [ ] **Step 3: Implement finalize + thin seams for mocking**

Add to `backend/guided_campaign.py`. The seams (`_load_knowledge`, `_load_playbooks`, `_account_and_pixel`, `_create_approval`, and a module-level `build_autonomous_campaign` import) keep the unit test free of Meta/network:

```python
from .opportunity_finder import build_autonomous_campaign  # module-level so tests can monkeypatch


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


def finalize(operator_key: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
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
        audience_override=guided.get("audienceSpec"),       # set only on the 'input' path
        creative_ids=list(guided.get("selectedCreatives") or []) or None,
        exclude_recent=(choice != "proven"),                # proven => include proven/recent winners
    )
    if approval is None:
        return {"text": "I couldn't find usable audience data yet — try the autonomous build later."}

    saved = _create_approval(approval)
    after = saved.get("after") or {}
    name = after.get("name") or "Test campaign"
    # Hand off to the existing agentic approve path (agap:approve -> execute_pending).
    set_pending(operator_key, {"kind": "agentic", "action": "create", "approvalId": saved["id"], "label": name},
                storage_dir=storage_dir)
    adsets = after.get("adsets") or []
    audiences = ", ".join(str(a.get("name", "")).replace(" - DRAFT", "") for a in adsets if a.get("name"))
    total = sum((float(a.get("daily_budget") or 0) / 100) for a in adsets)
    return {
        "text": (f"Here's the proposed PAUSED campaign — <b>{name}</b>\n"
                 f"Audiences: {audiences or 'top picks'}\nBudget: ${total:,.0f}/day total\n\n"
                 "Nothing is created until you approve."),
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": "agap:approve"},
            {"text": "✖️ Reject", "callback_data": "agap:reject"},
        ]]},
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/guided_campaign.py backend/test_guided_campaign.py
git commit -m "feat: guided campaign flow — finalize into the existing approve path"
```

---

### Task 5: Wire into Telegram (tool repoint + callback dispatch + audience-text turn)

**Files:**
- Modify: `backend/agentic_chat.py:158-165` (tool schema), `:213-214` (dispatch), `:288-327` (`_create_test_campaign`)
- Modify: `backend/routers/telegram.py` (callback action router ~756-789; free-text fallthrough ~880-905)
- Test: `backend/test_guided_campaign_api.py` (new)

- [ ] **Step 1: Write the failing integration tests**

```python
# backend/test_guided_campaign_api.py
"""Guided creation through the Telegram command endpoint, with realistic
callback payloads (callback_query.message.from = the bot)."""

import importlib
import json

from fastapi.testclient import TestClient


def _bind(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    members = [{"userId": "42", "username": "owner", "role": "owner", "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}]
    (tmp_path / "members.json").write_text(json.dumps(members), encoding="utf-8")
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("PENDING_CONTEXT_STORE_PATH", str(storage / "pending_context.json"))
    for var in ("TELEGRAM_COMMAND_SECRET", "TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ALLOWED_CHAT_IDS", "TELEGRAM_ADMIN_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    import backend.members_store as ms, backend.access_control as ac
    importlib.reload(ms); importlib.reload(ac)
    import backend.telegram_outbound as to
    sent = []
    monkeypatch.setattr(to, "send_telegram_message_sync", lambda text, **kw: sent.append((text, kw)) or {"ok": True})
    for fn in ("answer_callback_query", "edit_message_reply_markup", "edit_message_text", "send_photo", "send_video"):
        monkeypatch.setattr(to, fn, lambda *a, **k: {"ok": True})
    from backend.app import app
    return TestClient(app), sent


def _cb(data):
    return {"callback_query": {"id": "c", "from": {"id": 42, "username": "owner"},
            "message": {"chat": {"id": 42}, "message_id": 5, "from": {"id": 999, "is_bot": True}}, "data": data}}


def test_audience_choice_callback_advances(monkeypatch, tmp_path):
    client, sent = _bind(monkeypatch, tmp_path)
    # Seed the guided pending directly (start() covered by unit tests).
    import backend.guided_campaign as gc
    from backend.pending_context_store import operator_key
    gc.start(operator_key(telegram_chat_id="42"))
    resp = client.post("/api/telegram/command", json=_cb("gcreate:aud:new"))
    assert resp.status_code == 200
    assert resp.json().get("denied") != "no_access"   # RBAC fix holds for the human
    assert any("creativ" in t.lower() for t, _ in sent)
```

Note: this test writes the guided pending to the **default** store path while the app uses the env-isolated one — set the guided pending through the same `PENDING_CONTEXT_STORE_PATH`. If `gc.start()` defaults to `STORAGE_DIR`, pass `storage_dir` matching the env, or call the endpoint that starts the flow. Prefer driving `start` via the tool path: post a free-text "create a campaign" first (Step 3 wires it), then assert the audience question was sent — that exercises the real entry. Adjust the test to that once Step 3 lands.

- [ ] **Step 2: Repoint the `create_test_campaign` tool**

In `backend/agentic_chat.py`, schema (line 158-165):

```python
    {
        "name": "create_test_campaign",
        "description": "Start building a brand-new PAUSED test campaign. By default this opens a GUIDED flow that asks the operator to choose the audience and creatives. Set autonomous=true ONLY when the operator explicitly says to create one 'on your own' / 'autonomously' / 'without asking'. Nothing is created until the operator approves.",
        "input_schema": {
            "type": "object",
            "properties": {
                "autonomous": {"type": "boolean", "description": "true only on explicit hands-off phrasing"},
                "note": {"type": "string"},
            },
        },
    },
```

Dispatch (line 213-214):

```python
    if name == "create_test_campaign":
        return _create_test_campaign(operator_key=operator_key, autonomous=bool(args.get("autonomous")))
```

`_create_test_campaign` (line 288): branch at the top:

```python
def _create_test_campaign(*, operator_key: str, autonomous: bool = False) -> dict[str, Any]:
    if not autonomous:
        from .guided_campaign import start
        out = start(operator_key)
        # Surface the question + buttons to the operator via the agentic reply path.
        return {"guided": True, "message": out["text"], "reply_markup": out["reply_markup"]}
    # ... existing autonomous body unchanged from here ...
```

The agentic reply path already sends `answer` + attaches `reply_markup` from the stashed pending (telegram.py:894-902). Because the guided `start` sets a `kind="guided_create"` pending (not `"agentic"`), update that send block to also surface a `guided` reply_markup. Simplest: have `_run_tool`'s result carry `reply_markup`, and in `telegram.py` after `agentic_reply`, if the tool returned a guided keyboard, send it. **Cleaner approach (do this):** don't route guided start through the model's free-text answer at all — detect the create intent before the agentic call (Step 3).

- [ ] **Step 3: Detect the create-campaign intent + audience-text turn in the router**

In `backend/routers/telegram.py`, in the free-text branch (before calling `agentic_reply`, ~line 880), add:

```python
    from ..pending_context_store import get_pending as _gp, operator_key as _ok
    from .. import guided_campaign
    _opk = _ok(telegram_chat_id=command.get("chatId"))
    _pend = _gp(_opk)
    # Mid-flow: the operator is answering the "specify audience" prompt.
    if _pend and _pend.get("kind") == "guided_create" and (_pend.get("guided") or {}).get("step") == "audience_text":
        out = guided_campaign.handle_audience_text(_opk, text)
        _send(command, out["text"], parse_mode="HTML", reply_markup=out.get("reply_markup"))
        if out.get("next") == "render_creatives":
            _render_guided_creatives(command, _opk)
        return {"ok": True, "telegram": command, "guided": "audience_text"}
```

Add the `gcreate` callback handler alongside the other `if action == ...` blocks (~after line 763):

```python
    if action == "gcreate":
        return _handle_guided(command, callback)
```

Implement `_handle_guided` and `_render_guided_creatives` in `telegram.py` (transport layer — sends messages, calls the state machine). `_handle_guided` parses the callback tail (`aud:proven|aud:new|aud:input`, `cre:toggle:<id>`, `cre:done`, `cre:auto`), calls the matching `guided_campaign` function, and sends/edits messages. `_render_guided_creatives` calls `guided_campaign.top_creatives_for_selection(load_knowledge_base())`, then for each sends a photo/video with a toggle button (reuse the `_send_creative_media` media logic), and a trailing control message with `✅ Use selected (N)` / `⚡ Use top 5`. On `cre:done`/`cre:auto`, call `guided_campaign.finalize(...)` and send its `text` + `reply_markup`.

`handle_audience_text` in `guided_campaign.py` — parse the free text into an audience override and advance:

```python
def handle_audience_text(operator_key: str, text: str, *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    guided = _guided(operator_key, storage_dir)
    if guided is None:
        return {"text": "That setup expired. Say \"create a campaign\" to start over.", "expired": True}
    spec = _parse_audience_text(text)   # interests/age/location heuristic; deterministic, no LLM
    guided["audienceSpec"] = [spec]
    guided["audienceChoice"] = "input"
    guided["step"] = "creatives"
    _save(operator_key, guided, storage_dir)
    return {"text": f"Got it — targeting: <b>{spec['name']}</b>. Now pick the creatives.", "next": "render_creatives"}
```

`_parse_audience_text` is a deterministic heuristic (split on commas; detect an age range like `25-34`; treat a known-city token as location; the rest as interests; `name` = the raw text trimmed). Keep it simple and unit-test it.

- [ ] **Step 4: Add a `_parse_audience_text` unit test**

```python
def test_parse_audience_text_extracts_age_and_interests():
    from backend.guided_campaign import _parse_audience_text
    spec = _parse_audience_text("business owners, 25-34, Tashkent")
    assert spec["ageRange"] == "25-34"
    assert "Tashkent" in (spec.get("locations") or [])
    assert any("business" in i.lower() for i in spec["interests"])
```

Implement `_parse_audience_text` to pass it.

- [ ] **Step 5: Run the API + parse tests + full regression**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_guided_campaign_api.py backend/test_guided_campaign.py backend/test_telegram_roles.py -v`
Then full: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: all PASS (baseline 540 + new). Fix the integration test's pending-store seeding per the Step-1 note if needed (drive `start` via the tool, not a direct call, so it writes to the env-isolated store).

- [ ] **Step 6: Commit**

```bash
git add backend/agentic_chat.py backend/routers/telegram.py backend/guided_campaign.py backend/test_guided_campaign_api.py backend/test_guided_campaign.py
git commit -m "feat: wire guided campaign flow into Telegram (tool + callbacks + audience text)"
```

---

### Task 6: Full verification

- [ ] **Step 1: Full backend regression**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: 0 failures (540 baseline + new guided tests).

- [ ] **Step 2: Manual trace (optional, no live writes)**

Simulate the full sequence against a local server with `/api/telegram/command`: free-text "create a campaign" → assert audience question; `gcreate:aud:new` → creatives rendered; `gcreate:cre:toggle:<id>` → count updates; `gcreate:cre:done` → proposal with Approve/Reject. Confirm no `no_access` at any step.

- [ ] **Step 3: Final commit**

```bash
git add -A && git commit -m "feat: guided campaign creation (spec 2026-06-13)"
```

Deployment is OUT of scope — production restart requires separate explicit operator authorization.

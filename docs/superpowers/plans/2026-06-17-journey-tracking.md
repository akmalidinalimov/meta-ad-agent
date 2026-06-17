# Per-Audience Journey Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-audience × per-CRM-stage funnel (bot start → form → … → Paid) sourced live from Bitrix24 (read-only) and ChatPlace bot-start relay events, joined by phone, exposed at `GET /api/crm/funnel` and rendered in the React dashboard behind `VITE_CRM_ENABLED`.

**Architecture:** Additive only. A new pure module `backend/crm_funnel.py` builds the matrix from already-normalized Bitrix records + funnel events (phone-join, audience inheritance, stage matrix, matchRate). `backend/bitrix_client.py` gains real paging + a date filter + deal support. `backend/chatplace_events.py` + `backend/funnel_events.py` learn to capture/persist `aud` + `phone` from the enriched START webhook. `app.py` adds the `GET /api/crm/funnel` endpoint (sibling of the existing `/api/crm/bitrix/*` family). The dashboard gets a `CrmFunnelByAudience` component gated by `VITE_CRM_ENABLED`. Live `:8000`, the Meta campaign, and the live bot flow are untouched; the only ChatPlace change (the START webhook JSON body) is handed to the user to apply, not done in code.

**Tech Stack:** Python 3.14 / FastAPI / httpx / pytest (backend); React 19 / Vite / TypeScript / vitest (frontend). Bitrix24 REST read-only methods only (`crm.lead.list`, `crm.deal.list`, `crm.status.list`).

**Safety rules (non-negotiable, from the spec):**
- All work on branch `feat/journey-tracking`. Never commit to the live branch (`codex/meta-agent`).
- Test on staging (a second backend process on `:8001`). Live `:8000`, the live bot/flow, and the Meta campaign stay untouched.
- Additive endpoints only. Do not change behavior or response shape of existing endpoints. Preserve the deployed auth layer + ingest exemptions on cutover.
- Bitrix calls are READ-ONLY (`*.list` / `*.get` / `*.fields` only). Never `*.add` / `*.update` / `*.delete`.
- Ask before any LIVE deploy.

---

## File Structure

- **Create** `backend/crm_funnel.py` — pure matrix logic: phone/username/aud normalization, audience index from events, `build_crm_funnel(...)`, bot-starts-by-audience. No I/O, no network. Fully unit-tested.
- **Create** `backend/test_crm_funnel.py` — unit tests for the pure logic.
- **Modify** `backend/bitrix_client.py` — add real paging + optional date filter to `fetch_bitrix_leads`; add `fetch_bitrix_deals` + `normalize_bitrix_deal` (deal stages reuse existing `fetch_bitrix_statuses(entity_id="DEAL_STAGE")`).
- **Modify** `backend/test_bitrix_client.py` — tests for paging, date filter, deals (existing tests must stay green).
- **Modify** `backend/chatplace_events.py` — add `aud` + `phone` field paths.
- **Modify** `backend/funnel_events.py` — persist `aud` + `phone`.
- **Modify** `backend/test_chatplace_events.py` / `backend/test_funnel_events.py` — cover aud/phone capture.
- **Modify** `backend/app.py` — add `GET /api/crm/funnel` (+ small TTL cache). Sibling to `/api/crm/bitrix/*`.
- **Modify** `backend/test_bitrix_api.py` (or new `backend/test_crm_funnel_api.py`) — endpoint test with `FakeBitrixTransport`.
- **Modify** `src/components/Dashboard.tsx` — `CrmFunnelByAudience` component + exported `buildAudienceRows` helper, gated by `VITE_CRM_ENABLED`, rendered under `<LiveFunnelRates />`.
- **Create** `src/components/crmFunnel.test.ts` — vitest for `buildAudienceRows`.
- **Modify** `.env.example` / `docs/BITRIX24_CRM_INTEGRATION.md` — document `BITRIX_PAID_STATUS_IDS` and `VITE_CRM_ENABLED`.
- **(Optional, Part 3.4)** `backend/crm_funnel_snapshot.py` + `POST /api/crm/funnel/snapshot` + `GET /api/crm/funnel/trend` — daily snapshot for stage-movement trends.

**Audience join (locked):** PHONE is primary (match on trailing 9 digits — UZ `+998XXXXXXXXX`), `@username` secondary, `utm_content` as a cross-check fallback. Audience is captured at bot-start (the ChatPlace referral-link `aud` variable, relayed via `/api/chatplace/events`). Unmatched leads → `unattributed`, reported honestly with `matchRate`.

**Stage model (unknown until Part 0 confirmed):** Do NOT hardcode stage IDs. Discover stages live via `crm.status.list` (ordered by `SORT`). Identify the terminal "Paid" stage via `BITRIX_PAID_STATUS_IDS` env (comma-separated, authoritative) with a label-keyword heuristic fallback. Expose `paidStageIds` in the response so coverage is auditable. Support `?entity=lead` (default) and `?entity=deal`.

---

## Task 0: Branch + baseline (preserve pre-existing working tree)

**Files:** none created; git only.

The working tree already contains an unrelated in-progress feature (live funnel rates / first-party START: `app.py`, `funnel_events.py`, `analysis_engine.py`, `meta_client.py`, `Dashboard.tsx`, `test_analysis_engine.py`, `.gitignore`). Those files overlap ours, so commit them first as a labeled baseline to keep feature diffs clean. Never commit on `codex/meta-agent`.

- [ ] **Step 1: Create the feature branch (carries working tree)**

```bash
git checkout -b feat/journey-tracking
git rev-parse --abbrev-ref HEAD   # expect: feat/journey-tracking
```

- [ ] **Step 2: Commit the pre-existing tracked changes as a baseline**

```bash
git add -u                        # tracked modifications only; leaves untracked spec .md files alone
git commit -m "chore: baseline pre-existing live-funnel-rates working tree on feature branch"
```

- [ ] **Step 3: Confirm a clean tree for tracked files**

```bash
git status --porcelain | grep -vE '^\?\?'   # expect: no output (only untracked ?? remain)
```

---

## Task 1: `crm_funnel.py` — phone/username/aud normalization (pure)

**Files:**
- Create: `backend/crm_funnel.py`
- Test: `backend/test_crm_funnel.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/test_crm_funnel.py
from backend.crm_funnel import normalize_phone, normalize_username, normalize_aud


def test_normalize_phone_matches_on_trailing_nine_digits():
    assert normalize_phone("+998901234567") == "901234567"
    assert normalize_phone("998 90 123 45 67") == "901234567"
    assert normalize_phone("901234567") == "901234567"
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_normalize_username_strips_at_and_tme_link():
    assert normalize_username("@Buyer_UZ") == "buyer_uz"
    assert normalize_username("https://t.me/buyer_uz") == "buyer_uz"
    assert normalize_username("") == ""


def test_normalize_aud_strips_src_and_vsl_prefixes():
    assert normalize_aud("src_ai") == "ai"
    assert normalize_aud("vsl_business") == "business"
    assert normalize_aud("IT") == "it"
    assert normalize_aud("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.crm_funnel'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/crm_funnel.py
from __future__ import annotations

import re
from typing import Any, Iterable

# Audiences we split by (match the ChatPlace src_<aud> tags / referral-link aud values).
KNOWN_AUDIENCES = ("ai", "business", "it", "original", "content")

# Substrings that identify a terminal "Paid"/"Won" stage label when BITRIX_PAID_STATUS_IDS
# is not configured. Uzbek / Russian / English; matched case-insensitively on the label.
PAID_NAME_KEYWORDS = ("paid", "to'l", "to‘l", "to'la", "оплач", "оплат", "won", "купил", "успешн")

_DIGITS = re.compile(r"\D+")


def normalize_phone(value: Any) -> str:
    """Canonical phone match key: the trailing 9 digits (the UZ subscriber number).

    Robust to '+998', '998', leading '0', spaces, and bare local numbers, so ChatPlace
    and Bitrix formats join cleanly without country-code mismatches.
    """
    digits = _DIGITS.sub("", str(value or ""))
    if not digits:
        return ""
    return digits[-9:] if len(digits) >= 9 else digits


def normalize_username(value: Any) -> str:
    text = str(value or "").strip().lstrip("@").lower()
    if "t.me/" in text:
        text = text.split("t.me/", 1)[1].strip("/")
    return text


def normalize_aud(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("src_", "vsl_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/crm_funnel.py backend/test_crm_funnel.py
git commit -m "feat(crm): phone/username/aud normalization helpers for funnel join"
```

---

## Task 2: `crm_funnel.py` — audience index + bot-starts-by-audience

**Files:**
- Modify: `backend/crm_funnel.py`
- Test: `backend/test_crm_funnel.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/test_crm_funnel.py
from backend.crm_funnel import build_audience_index, count_bot_starts_by_audience


def _events():
    return [
        {"eventName": "bot_start", "aud": "ai", "phone": "+998901112233", "telegramUsername": "@ai_buyer", "telegramUserId": "tg1"},
        {"eventName": "bot_start", "aud": "src_business", "phone": "998907778899", "telegramUserId": "tg2"},
        {"eventName": "bot_start", "phone": "+998901112233", "telegramUserId": "tg1"},  # later, no aud → must not erase 'ai'
        {"eventName": "vsl_key_message_sent", "aud": "it", "phone": "+998905556677"},   # non-start still indexable
    ]


def test_build_audience_index_first_seen_audience_wins():
    index = build_audience_index(_events())
    assert index["byPhone"]["901112233"] == "ai"
    assert index["byPhone"]["907778899"] == "business"
    assert index["byUsername"]["ai_buyer"] == "ai"


def test_count_bot_starts_by_audience_dedupes_by_identity():
    counts = count_bot_starts_by_audience(_events())
    assert counts["ai"] == 1          # tg1 counted once despite two starts
    assert counts["business"] == 1
    assert counts["it"] == 0          # 'it' came from a non-bot_start event
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_audience_index'`.

- [ ] **Step 3: Write minimal implementation (append to `backend/crm_funnel.py`)**

```python
def build_audience_index(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """phone->aud and username->aud lookup maps built from funnel events.

    First-seen audience wins (setdefault), so a later audience-less duplicate start can
    never erase the audience captured at the original bot start.
    """
    by_phone: dict[str, str] = {}
    by_username: dict[str, str] = {}
    for event in events:
        aud = normalize_aud(event.get("aud") or event.get("segment"))
        if aud not in KNOWN_AUDIENCES:
            continue
        phone = normalize_phone(event.get("phone"))
        if phone:
            by_phone.setdefault(phone, aud)
        username = normalize_username(event.get("telegramUsername"))
        if username:
            by_username.setdefault(username, aud)
    return {"byPhone": by_phone, "byUsername": by_username}


def count_bot_starts_by_audience(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Unique bot starts per audience, deduped by Telegram user (then phone, then visitor)."""
    seen: dict[str, set[str]] = {aud: set() for aud in KNOWN_AUDIENCES}
    for event in events:
        if event.get("eventName") != "bot_start":
            continue
        aud = normalize_aud(event.get("aud") or event.get("segment"))
        if aud not in KNOWN_AUDIENCES:
            continue
        identity = event.get("telegramUserId") or normalize_phone(event.get("phone")) or event.get("visitorId")
        if identity:
            seen[aud].add(str(identity))
    return {aud: len(ids) for aud, ids in seen.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/crm_funnel.py backend/test_crm_funnel.py
git commit -m "feat(crm): audience index + bot-starts-by-audience from funnel events"
```

---

## Task 3: `crm_funnel.py` — paid-stage resolution + `build_crm_funnel` matrix

**Files:**
- Modify: `backend/crm_funnel.py`
- Test: `backend/test_crm_funnel.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/test_crm_funnel.py
from backend.crm_funnel import resolve_paid_stage_ids, build_crm_funnel

STAGES = [{"id": "NEW", "name": "Ne obrabotinniy"}, {"id": "CONTACTED", "name": "Contacted"},
          {"id": "QUALIFIED", "name": "Qualified"}, {"id": "PAID", "name": "To'lov qilindi"}]


def test_resolve_paid_stage_ids_prefers_config_over_heuristic():
    assert resolve_paid_stage_ids(STAGES, configured_ids=["QUALIFIED"]) == {"QUALIFIED"}
    assert resolve_paid_stage_ids(STAGES, configured_ids=None) == {"PAID"}  # keyword "to'l"


def test_build_crm_funnel_matrix_joins_by_phone_and_counts_paid():
    records = [
        {"stage": "PAID", "phone": "+998901112233", "telegramUsername": "", "utmContent": ""},      # -> ai (phone)
        {"stage": "NEW", "phone": "", "telegramUsername": "@ai_buyer", "utmContent": ""},            # -> ai (username)
        {"stage": "CONTACTED", "phone": "", "telegramUsername": "", "utmContent": "business"},       # -> business (utm)
        {"stage": "NEW", "phone": "+998000000000", "telegramUsername": "", "utmContent": ""},        # -> unattributed
    ]
    events = [
        {"eventName": "bot_start", "aud": "ai", "phone": "+998901112233", "telegramUsername": "@ai_buyer", "telegramUserId": "tg1"},
    ]
    out = build_crm_funnel(records, stages=STAGES, events=events, paid_status_ids=None, days=30, refreshed_at="T")
    assert out["stages"] == ["NEW", "CONTACTED", "QUALIFIED", "PAID"]
    assert out["paidStageIds"] == ["PAID"]
    assert out["audiences"]["ai"]["PAID"] == 1
    assert out["audiences"]["ai"]["NEW"] == 1
    assert out["audiences"]["ai"]["submits"] == 2
    assert out["audiences"]["ai"]["paid"] == 1
    assert out["audiences"]["ai"]["paidRate"] == 0.5
    assert out["audiences"]["business"]["CONTACTED"] == 1
    assert out["audiences"]["unattributed"]["NEW"] == 1
    assert out["matchRate"] == 0.75   # 3 of 4 matched
    assert out["audiences"]["ai"]["botStarts"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_crm_funnel'`.

- [ ] **Step 3: Write minimal implementation (append to `backend/crm_funnel.py`)**

```python
def resolve_paid_stage_ids(stages: list[dict[str, Any]], *, configured_ids: list[str] | None = None) -> set[str]:
    """Stage ids that count as 'Paid'. Explicit config (BITRIX_PAID_STATUS_IDS) wins;
    otherwise fall back to a label-keyword heuristic. May be empty (paid stage unknown)."""
    if configured_ids:
        configured = {s.strip() for s in configured_ids if s and s.strip()}
        if configured:
            return configured
    paid: set[str] = set()
    for stage in stages:
        name = str(stage.get("name") or "").lower()
        if any(keyword in name for keyword in PAID_NAME_KEYWORDS):
            paid.add(str(stage.get("id")))
    return paid


def _join_audience(record: dict[str, Any], by_phone: dict[str, str], by_username: dict[str, str]) -> str:
    phone = normalize_phone(record.get("phone"))
    if phone and phone in by_phone:
        return by_phone[phone]
    username = normalize_username(record.get("telegramUsername"))
    if username and username in by_username:
        return by_username[username]
    aud = normalize_aud(record.get("utmContent"))   # cross-check fallback
    return aud if aud in KNOWN_AUDIENCES else ""


def build_crm_funnel(
    records: list[dict[str, Any]],
    *,
    stages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    paid_status_ids: list[str] | None = None,
    days: int | None = None,
    source: str = "bitrix",
    refreshed_at: str = "",
) -> dict[str, Any]:
    """Per-audience × per-stage matrix. records are normalized Bitrix leads/deals."""
    index = build_audience_index(events)
    by_phone, by_username = index["byPhone"], index["byUsername"]
    bot_starts = count_bot_starts_by_audience(events)

    stage_ids = [str(s.get("id")) for s in stages if str(s.get("id") or "")]
    stage_labels = {str(s.get("id")): str(s.get("name") or s.get("id")) for s in stages}
    for record in records:                       # append any stage seen on records but not discovered
        sid = str(record.get("stage") or "")
        if sid and sid not in stage_ids:
            stage_ids.append(sid)
            stage_labels.setdefault(sid, sid)

    paid_ids = resolve_paid_stage_ids(
        [{"id": sid, "name": stage_labels[sid]} for sid in stage_ids], configured_ids=paid_status_ids
    )

    buckets = list(KNOWN_AUDIENCES) + ["unattributed"]
    rows = {aud: {sid: 0 for sid in stage_ids} for aud in buckets}

    matched = 0
    total = 0
    for record in records:
        sid = str(record.get("stage") or "")
        if not sid:
            continue
        total += 1
        aud = _join_audience(record, by_phone, by_username)
        if aud in KNOWN_AUDIENCES:
            matched += 1
        else:
            aud = "unattributed"
        rows[aud][sid] = rows[aud].get(sid, 0) + 1

    audiences: dict[str, Any] = {}
    for aud in buckets:
        counts = rows[aud]
        submits = sum(counts.values())
        paid = sum(count for sid, count in counts.items() if sid in paid_ids)
        starts = bot_starts.get(aud, 0)
        entry = dict(counts)
        entry["submits"] = submits
        entry["paid"] = paid
        entry["botStarts"] = starts
        entry["paidRate"] = round(paid / submits, 4) if submits else 0.0
        entry["paidRatePerStart"] = round(paid / starts, 4) if starts else 0.0
        audiences[aud] = entry

    return {
        "range": {"days": days},
        "stages": stage_ids,
        "stageLabels": stage_labels,
        "paidStageIds": sorted(paid_ids),
        "audiences": audiences,
        "matchRate": round(matched / total, 4) if total else 0.0,
        "source": source,
        "refreshedAt": refreshed_at,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/test_crm_funnel.py -q`
Expected: PASS (all crm_funnel tests).

- [ ] **Step 5: Commit**

```bash
git add backend/crm_funnel.py backend/test_crm_funnel.py
git commit -m "feat(crm): build_crm_funnel per-audience x per-stage matrix with phone-join + matchRate"
```

---

## Task 4: `bitrix_client.py` — real paging + date filter on leads

**Files:**
- Modify: `backend/bitrix_client.py:69-79`
- Test: `backend/test_bitrix_client.py`

The existing test `test_fetch_bitrix_leads_uses_crm_lead_list` asserts the EXACT single call `("crm.lead.list", {"order": {"DATE_CREATE": "DESC"}, "select": ["*", "UF_*"], "start": 0})`. The new implementation MUST preserve this when `days=None` and the transport returns no `next` key. Paging adds calls only when the payload carries `next`; the date filter key is added only when `days` is given.

- [ ] **Step 1: Write the failing tests (append to `backend/test_bitrix_client.py`)**

```python
class PagingBitrixTransport:
    def __init__(self):
        self.calls = []
    async def call(self, method, params):
        self.calls.append((method, params))
        start = params.get("start", 0)
        if start == 0:
            return {"result": [{"ID": "1", "STATUS_ID": "NEW"}], "next": 50}
        return {"result": [{"ID": "2", "STATUS_ID": "NEW"}]}


def test_fetch_bitrix_leads_follows_next_paging():
    transport = PagingBitrixTransport()
    leads = asyncio.run(fetch_bitrix_leads(transport=transport, limit=None))
    assert [c[1]["start"] for c in transport.calls] == [0, 50]
    assert [lead["crmLeadId"] for lead in leads] == ["1", "2"]


def test_fetch_bitrix_leads_adds_date_filter_when_days_given():
    transport = PagingBitrixTransport()
    asyncio.run(fetch_bitrix_leads(transport=transport, days=7, limit=None))
    first = transport.calls[0][1]
    assert ">=DATE_CREATE" in first["filter"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/test_bitrix_client.py -q`
Expected: FAIL — `fetch_bitrix_leads() got an unexpected keyword argument 'days'`.

- [ ] **Step 3: Replace `fetch_bitrix_leads` (`backend/bitrix_client.py:69-79`)**

```python
from datetime import date, timedelta

_MAX_PAGES = 50  # backstop: 50 pages * 50 rows = 2500 leads/deals per range


def _date_filter(days: int | None) -> dict[str, str] | None:
    if not days:
        return None
    since = (date.today() - timedelta(days=days)).isoformat()
    return {">=DATE_CREATE": since}


async def _fetch_paged(
    *, transport: BitrixTransport, method: str, days: int | None, limit: int | None
) -> list[dict[str, Any]]:
    filter_ = _date_filter(days)
    rows: list[dict[str, Any]] = []
    start = 0
    for _ in range(_MAX_PAGES):
        params: dict[str, Any] = {"order": {"DATE_CREATE": "DESC"}, "select": ["*", "UF_*"], "start": start}
        if filter_:
            params["filter"] = filter_
        payload = await transport.call(method, params)
        batch = payload.get("result", [])
        rows.extend(batch)
        nxt = payload.get("next")
        if not batch or nxt is None:
            break
        if limit is not None and len(rows) >= limit:
            break
        start = nxt
    return rows[:limit] if limit is not None else rows


async def fetch_bitrix_leads(
    *, transport: BitrixTransport, limit: int | None = 100, days: int | None = None
) -> list[dict[str, Any]]:
    rows = await _fetch_paged(transport=transport, method="crm.lead.list", days=days, limit=limit)
    return [normalize_bitrix_lead(row) for row in rows]
```

- [ ] **Step 4: Run to verify the new and existing lead tests pass**

Run: `python -m pytest backend/test_bitrix_client.py -q`
Expected: PASS (existing exact-call test still green because `days=None` adds no filter and the fake returns no `next`).

- [ ] **Step 5: Commit**

```bash
git add backend/bitrix_client.py backend/test_bitrix_client.py
git commit -m "feat(bitrix): real paging + optional date filter on lead reads (read-only)"
```

---

## Task 5: `bitrix_client.py` — deal reads (`?entity=deal` support)

**Files:**
- Modify: `backend/bitrix_client.py`
- Test: `backend/test_bitrix_client.py`

Deal stages reuse the existing `fetch_bitrix_statuses(entity_id="DEAL_STAGE")`; we only add a deal fetcher + normalizer. Stage comes from `STAGE_ID`.

- [ ] **Step 1: Write the failing test (append to `backend/test_bitrix_client.py`)**

```python
from backend.bitrix_client import fetch_bitrix_deals, normalize_bitrix_deal


def test_normalize_bitrix_deal_reads_stage_id_and_utm():
    out = normalize_bitrix_deal({"ID": "5", "STAGE_ID": "C1:WON", "PHONE": [{"VALUE": "+998901112233"}], "UTM_CONTENT": "ai"})
    assert out["crmLeadId"] == "5"
    assert out["stage"] == "C1:WON"
    assert out["phone"] == "+998901112233"
    assert out["utmContent"] == "ai"


def test_fetch_bitrix_deals_uses_crm_deal_list():
    transport = PagingBitrixTransport()
    deals = asyncio.run(fetch_bitrix_deals(transport=transport, limit=None))
    assert transport.calls[0][0] == "crm.deal.list"
    assert deals[0]["crmLeadId"] == "1"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/test_bitrix_client.py -q`
Expected: FAIL — `cannot import name 'fetch_bitrix_deals'`.

- [ ] **Step 3: Implement (append to `backend/bitrix_client.py`)**

```python
async def fetch_bitrix_deals(
    *, transport: BitrixTransport, limit: int | None = 100, days: int | None = None
) -> list[dict[str, Any]]:
    rows = await _fetch_paged(transport=transport, method="crm.deal.list", days=days, limit=limit)
    return [normalize_bitrix_deal(row) for row in rows]


def normalize_bitrix_deal(row: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_bitrix_lead(row)
    normalized["stage"] = row.get("STAGE_ID") or row.get("STATUS_ID") or ""
    normalized["crm"] = "bitrix24:deal"
    return normalized
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_bitrix_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/bitrix_client.py backend/test_bitrix_client.py
git commit -m "feat(bitrix): read-only deal list + deal normalizer for funnel entity=deal"
```

---

## Task 6: `GET /api/crm/funnel` endpoint (+ TTL cache)

**Files:**
- Modify: `backend/app.py` (imports near line 26-32; new endpoint near the `/api/crm/*` block ~line 819)
- Test: Create `backend/test_crm_funnel_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/test_crm_funnel_api.py
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app


class FakeFunnelTransport:
    async def call(self, method, params):
        if method == "crm.status.list":
            return {"result": [
                {"ID": "1", "ENTITY_ID": "STATUS", "STATUS_ID": "NEW", "NAME": "New", "SORT": "10"},
                {"ID": "2", "ENTITY_ID": "STATUS", "STATUS_ID": "PAID", "NAME": "To'lov qilindi", "SORT": "20"},
            ]}
        return {"result": [
            {"ID": "101", "STATUS_ID": "PAID", "PHONE": [{"VALUE": "+998901112233"}]},
            {"ID": "102", "STATUS_ID": "NEW", "PHONE": [{"VALUE": "+998900000000"}]},
        ]}


def test_crm_funnel_groups_by_audience_via_phone_join(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "funnel_events.jsonl").write_text(
        '{"eventName":"bot_start","aud":"ai","phone":"+998901112233","telegramUserId":"tg1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", "https://example.bitrix24.com/rest/1/secret/")
    monkeypatch.setattr(app_module, "build_bitrix_transport", lambda config: FakeFunnelTransport())
    monkeypatch.setattr(app_module, "FUNNEL_EVENTS_STORAGE_DIR", storage)
    app_module._CRM_FUNNEL_CACHE.clear()
    client = TestClient(app)

    res = client.get("/api/crm/funnel?days=30")
    body = res.json()

    assert res.status_code == 200
    assert body["ok"] is True
    assert body["audiences"]["ai"]["PAID"] == 1
    assert body["audiences"]["unattributed"]["NEW"] == 1
    assert body["matchRate"] == 0.5
    assert body["paidStageIds"] == ["PAID"]


def test_crm_funnel_reports_unconfigured_without_calling_bitrix(monkeypatch):
    monkeypatch.delenv("BITRIX24_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("BITRIX24_PORTAL_URL", raising=False)
    monkeypatch.delenv("BITRIX24_USER_ID", raising=False)
    monkeypatch.delenv("BITRIX24_WEBHOOK_KEY", raising=False)
    app_module._CRM_FUNNEL_CACHE.clear()
    client = TestClient(app)

    res = client.get("/api/crm/funnel?days=30")
    assert res.status_code == 200
    assert res.json()["ok"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/test_crm_funnel_api.py -q`
Expected: FAIL — 404 / attribute errors (endpoint + cache + storage hook absent).

- [ ] **Step 3: Implement**

In `backend/app.py` extend imports:
```python
from .bitrix_client import (
    HttpBitrixTransport, fetch_bitrix_deals, fetch_bitrix_leads, fetch_bitrix_statuses, get_bitrix_config,
)
from .crm_funnel import build_crm_funnel
from .funnel_events import build_funnel_summary, count_bot_starts, load_funnel_events, save_funnel_event
from .funnel_events import STORAGE_DIR as FUNNEL_EVENTS_STORAGE_DIR
```

Add near the `/api/crm/*` block (after `/api/crm/leads`, ~line 821):
```python
_CRM_FUNNEL_CACHE: dict[str, Any] = {}
_CRM_FUNNEL_TTL_SECONDS = 90


@app.get("/api/crm/funnel")
async def crm_funnel(days: int = 30, entity: str = "lead") -> dict[str, Any]:
    """Per-audience x per-CRM-stage funnel, read-only from Bitrix24, joined to bot
    starts by phone. Additive sibling of /api/crm/bitrix/*. Never writes to Bitrix."""
    config = get_bitrix_config()
    if not config.is_configured:
        return {"ok": False, "error": "Bitrix24 webhook URL is not configured.",
                "audiences": {}, "stages": [], "stageLabels": {}, "paidStageIds": [], "matchRate": 0.0}

    cache_key = f"{entity}:{days}"
    cached = _CRM_FUNNEL_CACHE.get(cache_key)
    now = datetime.now(timezone.utc)
    if cached and (now - cached["at"]).total_seconds() < _CRM_FUNNEL_TTL_SECONDS:
        return cached["payload"]

    transport = build_bitrix_transport(config)
    try:
        if entity == "deal":
            records = await fetch_bitrix_deals(transport=transport, days=days, limit=None)
            stages_raw = await fetch_bitrix_statuses(transport=transport, entity_id="DEAL_STAGE")
        else:
            records = await fetch_bitrix_leads(transport=transport, days=days, limit=None)
            stages_raw = await fetch_bitrix_statuses(transport=transport, entity_id="STATUS")
    except Exception as exc:  # noqa: BLE001 - surface a sanitized 502
        raise HTTPException(status_code=502, detail=f"Bitrix24 funnel read failed: {exc}") from exc

    stages = [{"id": s["statusId"], "name": s["name"]} for s in stages_raw]
    events = load_funnel_events(storage_dir=FUNNEL_EVENTS_STORAGE_DIR)
    paid_ids = [s.strip() for s in os.getenv("BITRIX_PAID_STATUS_IDS", "").split(",") if s.strip()]
    payload = build_crm_funnel(
        records, stages=stages, events=events, paid_status_ids=paid_ids or None,
        days=days, refreshed_at=now.isoformat(),
    )
    payload["ok"] = True
    payload["entity"] = entity
    _CRM_FUNNEL_CACHE[cache_key] = {"at": now, "payload": payload}
    return payload
```

(`datetime`, `timezone`, `os` are already imported; `build_bitrix_transport` is defined at ~line 824.)

- [ ] **Step 4: Run endpoint + full CRM suite**

Run: `python -m pytest backend/test_crm_funnel_api.py backend/test_bitrix_api.py backend/test_bitrix_client.py -q`
Expected: PASS (new endpoint tests + all existing CRM tests green — additive, nothing else changed).

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/test_crm_funnel_api.py
git commit -m "feat(api): GET /api/crm/funnel per-audience stage matrix (read-only, cached)"
```

---

## Task 7: Part 3.1 — capture `aud` + `phone` from the enriched START webhook

**Files:**
- Modify: `backend/chatplace_events.py:9-64`
- Modify: `backend/funnel_events.py:16-50`
- Test: `backend/test_chatplace_events.py`

The ChatPlace START webhook body (applied by the user in the ChatPlace UI — NOT by us) will be:
```json
{ "event_name":"bot_start", "telegram_user_id":"{{clientId}}",
  "aud":"{{aud}}", "username":"{{username}}", "phone":"{{Phone}}", "ts":"{{createdAt}}" }
```
Backend must accept and persist `aud` + `phone` (username already maps to `telegram_username`).

- [ ] **Step 1: Write the failing test (append to `backend/test_chatplace_events.py`)**

```python
def test_chatplace_event_captures_aud_and_phone(tmp_path):
    event = normalize_chatplace_event({
        "event_name": "bot_start",
        "telegram_user_id": "tg_99",
        "aud": "business",
        "username": "buyer_uz",
        "phone": "+998901112233",
    })
    assert event["aud"] == "business"
    assert event["phone"] == "+998901112233"

    saved = save_funnel_event(event, storage_dir=tmp_path / "storage")
    assert saved["aud"] == "business"
    assert saved["phone"] == "+998901112233"
    assert saved["telegramUsername"] == "buyer_uz"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest backend/test_chatplace_events.py::test_chatplace_event_captures_aud_and_phone -q`
Expected: FAIL — `KeyError: 'aud'`.

- [ ] **Step 3: Implement**

In `backend/chatplace_events.py`, add to `FIELD_PATHS` (after `fbclid`):
```python
    "aud": ["aud", "audience", "variables.aud", "variables.audience"],
    "phone": ["phone", "Phone", "client.phone", "variables.phone", "variables.Phone"],
```

In `backend/funnel_events.py`, add to `FIELD_MAP` (after `fbclid`):
```python
    "aud": "aud",
    "phone": "phone",
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest backend/test_chatplace_events.py backend/test_funnel_events.py -q`
Expected: PASS (new test + all existing chatplace/funnel tests).

- [ ] **Step 5: Commit**

```bash
git add backend/chatplace_events.py backend/funnel_events.py backend/test_chatplace_events.py
git commit -m "feat(funnel): capture aud + phone from enriched ChatPlace START webhook"
```

---

## Task 8: Backend regression + staging verification

**Files:** none modified; verification only.

- [ ] **Step 1: Full backend suite is green**

Run: `python -m pytest backend/ -q`
Expected: PASS (all tests, including pre-existing). Note any unrelated failures explicitly.

- [ ] **Step 2: Launch staging on :8001 (live :8000 untouched — it is the remote OCI VM)**

Run (background): `python -m uvicorn backend.app:app --port 8001`

- [ ] **Step 3: Hit the endpoint (read-only Bitrix via local .env webhook)**

Run: `Invoke-RestMethod 'http://127.0.0.1:8001/api/crm/funnel?days=30' | ConvertTo-Json -Depth 6`
Expected: JSON matching the contract (`ok`, `stages`, `audiences` incl. `unattributed`, `matchRate`, `paidStageIds`, `refreshedAt`). Record the output as evidence in VERIFICATION notes. Confirm `crm.lead.list`/`crm.status.list` are the only methods called (read-only).

- [ ] **Step 4: Regression — existing endpoints unchanged**

Run: `Invoke-RestMethod 'http://127.0.0.1:8001/api/funnel/rates?days=30'` and `Invoke-RestMethod 'http://127.0.0.1:8001/api/crm/bitrix/status'`
Expected: same shapes as before this branch.

- [ ] **Step 5: Commit verification notes**

```bash
git add docs/superpowers/plans/2026-06-17-journey-tracking.md
git commit -m "docs: journey-tracking staging verification evidence"
```

---

## Task 9: Part 4 — `CrmFunnelByAudience` dashboard component

**Files:**
- Modify: `src/components/Dashboard.tsx` (render under `<LiveFunnelRates />` at line 607; add component + helper near `LiveFunnelRates` ~line 673-792)
- Test: Create `src/components/crmFunnel.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/components/crmFunnel.test.ts
import { describe, expect, it } from 'vitest'
import { buildAudienceRows, type CrmFunnelPayload } from './Dashboard'

const payload: CrmFunnelPayload = {
  ok: true,
  stages: ['NEW', 'PAID'],
  stageLabels: { NEW: 'New', PAID: "To'lov" },
  paidStageIds: ['PAID'],
  matchRate: 0.5,
  audiences: {
    ai: { NEW: 1, PAID: 1, submits: 2, paid: 1, botStarts: 4, paidRate: 0.5, paidRatePerStart: 0.25 },
    unattributed: { NEW: 3, PAID: 0, submits: 3, paid: 0, botStarts: 0, paidRate: 0, paidRatePerStart: 0 },
  },
}

describe('buildAudienceRows', () => {
  it('orders known audiences first, unattributed last, and carries paid metrics', () => {
    const rows = buildAudienceRows(payload)
    expect(rows[0].audience).toBe('ai')
    expect(rows[rows.length - 1].audience).toBe('unattributed')
    expect(rows[0].cells.map((c) => c.count)).toEqual([1, 1])
    expect(rows[0].paidRatePct).toBe('50%')
  })
  it('returns [] when payload has no audiences', () => {
    expect(buildAudienceRows({ ...payload, audiences: {} })).toEqual([])
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm run test -- crmFunnel`
Expected: FAIL — `buildAudienceRows` / `CrmFunnelPayload` not exported.

- [ ] **Step 3: Implement in `src/components/Dashboard.tsx`**

Add exported types + helper (near `LiveFunnelRatesPayload`, ~line 681):
```ts
export interface CrmFunnelAudience {
  submits: number; paid: number; botStarts: number; paidRate: number; paidRatePerStart: number
  [stageId: string]: number
}
export interface CrmFunnelPayload {
  ok: boolean
  stages: string[]
  stageLabels: Record<string, string>
  paidStageIds: string[]
  audiences: Record<string, CrmFunnelAudience>
  matchRate: number
  refreshedAt?: string
  error?: string
}

const AUDIENCE_ORDER = ['ai', 'business', 'it', 'original', 'content']

export function buildAudienceRows(payload: CrmFunnelPayload) {
  const auds = Object.keys(payload.audiences ?? {})
  if (auds.length === 0) return []
  const ordered = [
    ...AUDIENCE_ORDER.filter((a) => a in payload.audiences),
    ...auds.filter((a) => !AUDIENCE_ORDER.includes(a) && a !== 'unattributed'),
    ...(payload.audiences.unattributed ? ['unattributed'] : []),
  ]
  return ordered.map((audience) => {
    const data = payload.audiences[audience]
    return {
      audience,
      botStarts: data.botStarts ?? 0,
      submits: data.submits ?? 0,
      paid: data.paid ?? 0,
      paidRatePct: `${Math.round((data.paidRate ?? 0) * 100)}%`,
      cells: payload.stages.map((sid) => ({ stageId: sid, count: Number(data[sid] ?? 0) })),
    }
  })
}
```

Add the component (after `LiveFunnelRates`, ~line 792):
```tsx
function CrmFunnelByAudience() {
  const [payload, setPayload] = useState<CrmFunnelPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [errored, setErrored] = useState(false)

  useEffect(() => {
    if (typeof fetch !== 'function') { setLoading(false); return }
    let active = true
    void fetch(liveFunnelApiUrl('/api/crm/funnel?days=30'))
      .then((r) => (r.ok ? r.json() : null))
      .then((data: CrmFunnelPayload | null) => {
        if (!active) return
        setPayload(data); setLoading(false); setErrored(data == null)
      })
      .catch(() => { if (active) { setErrored(true); setLoading(false) } })
    return () => { active = false }
  }, [])

  if (loading) return <section className="panel"><PanelHeading eyebrow="CRM" title="Per-audience funnel to Paid" icon={Target} /><p className="muted">Loading CRM funnel…</p></section>
  if (errored || !payload || payload.ok === false) {
    return <section className="panel"><PanelHeading eyebrow="CRM" title="Per-audience funnel to Paid" icon={Target} /><p className="muted">{payload?.error ?? 'CRM funnel unavailable. Configure Bitrix24 and retry.'}</p></section>
  }
  const rows = buildAudienceRows(payload)
  if (rows.length === 0) return <section className="panel"><PanelHeading eyebrow="CRM" title="Per-audience funnel to Paid" icon={Target} /><p className="muted">No CRM leads in range yet.</p></section>

  return (
    <section className="panel panel-wide" aria-label="CRM funnel by audience">
      <PanelHeading eyebrow="CRM" title="Per-audience funnel to Paid" icon={Target} />
      <p className="muted">Match rate {Math.round(payload.matchRate * 100)}% · phone-join · last 30 days</p>
      <div className="crm-funnel-scroll">
        <table className="crm-funnel-table">
          <thead>
            <tr>
              <th>Audience</th><th>Bot starts</th>
              {payload.stages.map((sid) => (
                <th key={sid} className={payload.paidStageIds.includes(sid) ? 'paid-col' : ''}>{payload.stageLabels[sid] ?? sid}</th>
              ))}
              <th>Paid rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.audience} className={row.audience === 'unattributed' ? 'unattributed-row' : ''}>
                <td>{row.audience}</td>
                <td>{formatNumber(row.botStarts)}</td>
                {row.cells.map((cell) => (
                  <td key={cell.stageId} className={payload.paidStageIds.includes(cell.stageId) ? 'paid-col' : ''}>{formatNumber(cell.count)}</td>
                ))}
                <td><strong>{row.paidRatePct}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
```

Gate it in `Overview` (line 607) so it never renders unless explicitly enabled:
```tsx
      <LiveFunnelRates />
      {import.meta.env.VITE_CRM_ENABLED === 'true' ? <CrmFunnelByAudience /> : null}
```

- [ ] **Step 4: Run frontend tests + typecheck**

Run: `npm run test -- crmFunnel` then `npx tsc -b --noEmit`
Expected: PASS; no type errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/Dashboard.tsx src/components/crmFunnel.test.ts
git commit -m "feat(dashboard): CrmFunnelByAudience matrix behind VITE_CRM_ENABLED"
```

---

## Task 10: Minimal styling + docs for the new flags

**Files:**
- Modify: `src/components/Dashboard.tsx` styles (wherever component CSS lives) OR the global stylesheet — add `.crm-funnel-table`, `.paid-col`, `.unattributed-row`, `.crm-funnel-scroll`, `.muted` if absent.
- Modify: `.env.example`, `docs/BITRIX24_CRM_INTEGRATION.md`

- [ ] **Step 1: Add styles** (match existing `.panel`/table conventions; `.paid-col` highlighted, `.crm-funnel-scroll { overflow-x: auto }`). Verify the table renders without layout break.

- [ ] **Step 2: Document the two new env knobs**

Append to `.env.example`:
```text
# Per-audience CRM funnel (Part 3/4). Comma-separated Bitrix stage IDs that count as "Paid".
# If unset, the funnel guesses by stage label keywords; set this once the sales team confirms.
BITRIX_PAID_STATUS_IDS=
```
And note in `docs/BITRIX24_CRM_INTEGRATION.md` that the React dashboard renders the per-audience matrix only when the frontend build has `VITE_CRM_ENABLED=true`, and that `GET /api/crm/funnel?days=N&entity=lead|deal` is the read-only source.

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/BITRIX24_CRM_INTEGRATION.md src/components/Dashboard.tsx
git commit -m "docs+style: CRM funnel env flags + table styling"
```

---

## Task 11: Dashboard staging verification (Chrome via /browse)

**Files:** none; verification only.

- [ ] **Step 1: Run dev server with the flag on** — `VITE_CRM_ENABLED=true VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev` (PowerShell: set env then `npm run dev`), backend staging still on :8001.
- [ ] **Step 2: Load the dashboard with `/browse`**, screenshot the CRM matrix, confirm numbers equal the `/api/crm/funnel` JSON. Toggle the flag off → section disappears, no layout break.
- [ ] **Step 3:** Record evidence; commit notes.

---

## Task 12 (OPTIONAL, Part 3.4): Daily snapshot + per-audience trend

**Files:**
- Create: `backend/crm_funnel_snapshot.py` (+ `backend/test_crm_funnel_snapshot.py`)
- Modify: `backend/app.py` — `POST /api/crm/funnel/snapshot` (compute + persist today's matrix, idempotent per UTC day) and `GET /api/crm/funnel/trend?days=N`.
- Modify: `src/components/Dashboard.tsx` — small per-audience movement-to-Paid trend.

Snapshot store: append `{date, audiences:{aud:{paid,submits,botStarts}}}` to `storage/crm_funnel_snapshots.jsonl`, one row per UTC day (overwrite same-day). Trend endpoint returns the per-day paid/submit series per audience. Only build this after Tasks 1–11 are solid; it is additive and independently testable. A scheduled task (cron) can POST the snapshot daily.

---

## Self-Review

- **Spec coverage:** Part 2.2 = N/A (no landing repo here — prerequisite the user confirmed). Part 3.1 = Task 7. Part 3.2 (matrix) = Tasks 1-6. Part 3.3 (phone-join) = Tasks 2-3, 6. Part 3.4 (snapshot) = Task 12 (optional). Part 4.1/4.2/4.3 = Tasks 9-11. Safety (branch/staging/additive/read-only) = Tasks 0, 6, 8, 11.
- **No live changes:** the only ChatPlace edit (START webhook body) is handed to the user (Task 7 note), not done in code. No Meta calls. No Bitrix writes. Live `:8000` is the remote VM; staging is local `:8001`.
- **Type consistency:** `build_crm_funnel` output keys (`stages`, `stageLabels`, `paidStageIds`, `audiences`, `matchRate`, `refreshedAt`) match the endpoint and the TS `CrmFunnelPayload`. `audiences[aud]` carries `submits/paid/botStarts/paidRate/paidRatePerStart` + per-stage counts in both Python and TS.
- **Existing tests preserved:** Task 4 keeps the exact-call lead test green (no filter / no extra calls when `days=None`).

## Execution Handoff

Inline execution (the user asked to "plan and execute accordingly" this session): proceed task-by-task with TDD, committing per task, running the suites at each step, and pausing only before any LIVE deploy.

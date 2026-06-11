# Lean Monitor Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cluttered Monitor view with a single-screen monitoring dashboard (KPI rail / trend+funnel / animated Agent Office), remove the web Chat tab and approval UI, and back the Agent Office with real backend job activity.

**Architecture:** A new backend `agent_activity` registry (in-process live state + persisted JSON event feed) is marked by real jobs (monitoring scan, opportunity finder, agentic chat, creative recommender) and served via `GET /api/agents/status`. The frontend gets a new `MonitorView` (KPI rail with complete-days deltas, one recharts trend, funnel bars) and a polling `AgentOffice` component. Chat/approval/hero/problems/insights UI and their CSS are deleted; backend chat/approval APIs stay (Telegram + MCP use them).

**Tech Stack:** FastAPI + pytest (backend), React 19 + TS + recharts + vitest/jsdom (frontend), plain CSS with existing design tokens.

**Spec:** `docs/superpowers/specs/2026-06-11-dashboard-monitor-redesign-design.md`

**Working directory:** `C:\Users\akmal\Documents\meta-ad-agent-review` (worktree, branch `feat/rbac-roles`). Recommended: create branch `feat/lean-monitor` off it before starting.

**Test commands (house rules):**
- Backend: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q` (blank the keys or ~5 no-key tests fail). Single file: same prefix + `python -m pytest backend/test_agent_activity.py -v`
- Frontend: `npm test -- --run` (vitest). Lint: `npm run lint`. Build: `npm run build`
- DOM tests need `// @vitest-environment jsdom` at the top; assert with `.toBeTruthy()` (jest-dom matchers are NOT set up)

---

## File structure

**Create (backend):**
- `backend/agent_activity.py` — registry: live working state + persisted events/last-active
- `backend/routers/agent_status.py` — `GET /api/agents/status`
- `backend/test_agent_activity.py`, `backend/test_agent_status_api.py`

**Modify (backend):**
- `backend/app.py` — mount router; begin/end hooks in `_monitoring_loop`
- `backend/agentic_chat.py` — analyst begin/end around the tool loop
- `backend/opportunity_finder.py` — creative begin/end around `build_recommended_creatives`
- `backend/targets_store.py` + `backend/routers/targets.py` — `weeklyBudgetTargetUsd` field

**Create (frontend):**
- `src/lib/monitorKpis.ts` + `src/lib/monitorKpis.test.ts` — KPI derivation with complete-days deltas
- `src/services/agentStatusProvider.ts` + `.test.ts` — typed fetch for agent status
- `src/components/dashboard/views/AgentOffice.tsx` + `.test.tsx` — scene + status list + feed + mobile strip
- `src/components/dashboard/views/MonitorView.tsx` + `.test.tsx` — the new single-screen view

**Modify (frontend):**
- `src/components/Dashboard.tsx` — remove chat/approvals/hero/problems/insights/details; render MonitorView; freshness stamp; nav helper
- `src/components/Dashboard.test.tsx` — rewrite (old tests cover deleted ApprovalQueue)
- `src/components/dashboard/views/SettingsView.tsx` — weekly budget target field
- `src/App.css` — new `.monitor-*` styles; delete dead style blocks

**Delete (frontend):**
- `src/services/agentChatProvider.ts`
- `src/services/agentTaskProvider.ts` + `src/services/agentTaskProvider.test.ts`
- `src/lib/operatorAttention.ts` + `src/lib/operatorAttention.test.ts`

---

### Task 1: Backend agent activity registry

**Files:**
- Create: `backend/agent_activity.py`
- Test: `backend/test_agent_activity.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_agent_activity.py
"""Agent activity registry — live working state + persisted event feed."""

from backend import agent_activity


def setup_function():
    agent_activity.reset_live_for_tests()


def test_begin_marks_agent_working():
    agent_activity.begin("monitor", "scanning ad sets")
    live = agent_activity.live_state()
    assert live["monitor"]["activity"] == "scanning ad sets"
    assert live["monitor"]["startedAt"]


def test_unknown_agent_id_is_ignored():
    agent_activity.begin("ghost", "haunting")
    assert agent_activity.live_state() == {}


def test_end_without_summary_clears_live_and_persists_nothing(tmp_path):
    agent_activity.begin("monitor", "scanning ad sets")
    agent_activity.end("monitor", None, storage_dir=tmp_path)
    assert agent_activity.live_state() == {}
    assert agent_activity.stored(storage_dir=tmp_path)["events"] == []


def test_end_with_summary_persists_event_and_last_active(tmp_path):
    agent_activity.begin("planner", "daily opportunity review")
    agent_activity.end("planner", "opportunity review completed", storage_dir=tmp_path)

    assert agent_activity.live_state() == {}
    data = agent_activity.stored(storage_dir=tmp_path)
    assert data["events"][0]["agentId"] == "planner"
    assert data["events"][0]["summary"] == "opportunity review completed"
    assert data["events"][0]["at"]
    assert data["lastActive"]["planner"]["summary"] == "opportunity review completed"


def test_end_without_begin_still_records_event(tmp_path):
    # e.g. a job that only reports completion
    agent_activity.end("analyst", "KPI digest sent to Telegram", storage_dir=tmp_path)
    data = agent_activity.stored(storage_dir=tmp_path)
    assert data["events"][0]["agentId"] == "analyst"


def test_events_are_capped(tmp_path):
    for i in range(60):
        agent_activity.end("analyst", f"run {i}", storage_dir=tmp_path)
    data = agent_activity.stored(storage_dir=tmp_path)
    assert len(data["events"]) == agent_activity.MAX_EVENTS
    assert data["events"][0]["summary"] == "run 59"  # newest first


def test_stored_handles_missing_file(tmp_path):
    assert agent_activity.stored(storage_dir=tmp_path) == {"events": [], "lastActive": {}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_agent_activity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.agent_activity'`

- [ ] **Step 3: Write the implementation**

```python
# backend/agent_activity.py
"""Agent activity registry for the dashboard's Agent Office.

Live "working" state is held in-process — it reflects *right now*, so losing it
on restart is correct. Completed work persists to storage/agent_activity.json
(a capped event feed plus per-agent last-active stamps) so the office still
shows recent history after a service restart.

Real jobs call begin()/end() around real work; the dashboard reads the
snapshot. An agent never shows "working" unless something is genuinely running.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_io import read_json, update_json

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
EVENTS_FILE = "agent_activity.json"
MAX_EVENTS = 50

AGENTS: dict[str, str] = {
    "monitor": "Monitor",
    "analyst": "Analyst",
    "planner": "Planner",
    "creative": "Creative",
}

_live: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(storage_dir: Path) -> Path:
    return storage_dir / EVENTS_FILE


def begin(agent_id: str, activity: str) -> None:
    """Mark an agent as working on `activity`. Unknown ids are ignored."""
    if agent_id not in AGENTS:
        return
    with _lock:
        _live[agent_id] = {"activity": activity, "startedAt": _now_iso()}


def end(agent_id: str, summary: str | None = None, *, storage_dir: Path = STORAGE_DIR) -> None:
    """Mark an agent as done. With a summary, persist a feed event and the
    last-active stamp; without one (skipped or failed runs) just clear the
    live state so nothing false lands in the feed."""
    if agent_id not in AGENTS:
        return
    with _lock:
        live = _live.pop(agent_id, None)
    if not summary:
        return
    at = _now_iso()
    activity = (live or {}).get("activity") or summary

    def mutate(data: dict[str, Any]) -> None:
        events = data.setdefault("events", [])
        events.insert(0, {"agentId": agent_id, "summary": summary, "at": at})
        del events[MAX_EVENTS:]
        data.setdefault("lastActive", {})[agent_id] = {
            "activity": activity,
            "summary": summary,
            "at": at,
        }

    update_json(_path(storage_dir), mutate, default={"events": [], "lastActive": {}})


def live_state() -> dict[str, dict[str, Any]]:
    with _lock:
        return {key: dict(value) for key, value in _live.items()}


def stored(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    payload = read_json(_path(storage_dir), None)
    if not isinstance(payload, dict):
        return {"events": [], "lastActive": {}}
    events = payload.get("events")
    last = payload.get("lastActive")
    return {
        "events": events if isinstance(events, list) else [],
        "lastActive": last if isinstance(last, dict) else {},
    }


def reset_live_for_tests() -> None:
    with _lock:
        _live.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_agent_activity.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agent_activity.py backend/test_agent_activity.py
git commit -m "feat: agent activity registry with persisted event feed"
```

---

### Task 2: `GET /api/agents/status` endpoint

**Files:**
- Create: `backend/routers/agent_status.py`
- Modify: `backend/app.py` (router import + include loop, ~lines 141–158 imports and 194–211 mount loop)
- Test: `backend/test_agent_status_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/test_agent_status_api.py
"""Agent status feed — session-guarded, viewer-readable."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMBERS_STORE_PATH", str(tmp_path / "members.json"))
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    monkeypatch.setenv("DASHBOARD_SESSION_AUTH", "true")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)

    from backend import members_store

    importlib.reload(members_store)
    members_store.list_members()  # seed owner from TELEGRAM_ADMIN_CHAT_ID
    members_store.add_member(user_id="100", role="viewer", added_by="42")

    from backend import agent_activity

    agent_activity.reset_live_for_tests()

    from backend import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def _cookie(sub):
    from backend.webapp_auth import make_session

    return {"session": make_session(sub)}


def test_unauthenticated_gets_401(client):
    assert client.get("/api/agents/status").status_code == 401


def test_viewer_can_read_status(client):
    resp = client.get("/api/agents/status", cookies=_cookie("tg:100"))
    assert resp.status_code == 200
    payload = resp.json()
    assert [agent["id"] for agent in payload["agents"]] == [
        "monitor",
        "analyst",
        "planner",
        "creative",
    ]
    assert "events" in payload
    assert payload["updatedAt"]


def test_working_agent_is_reported_with_activity(client):
    from backend import agent_activity

    agent_activity.begin("monitor", "scanning ad sets")
    try:
        resp = client.get("/api/agents/status", cookies=_cookie("admin"))
        monitor = next(a for a in resp.json()["agents"] if a["id"] == "monitor")
        assert monitor["state"] == "working"
        assert monitor["activity"] == "scanning ad sets"
        assert monitor["sinceSeconds"] >= 0
    finally:
        agent_activity.end("monitor")  # no summary: nothing persisted


def test_idle_agent_has_no_activity(client):
    resp = client.get("/api/agents/status", cookies=_cookie("admin"))
    analyst = next(a for a in resp.json()["agents"] if a["id"] == "analyst")
    assert analyst["state"] in ("idle", "scheduled")
    assert analyst["activity"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_agent_status_api.py -v`
Expected: FAIL — 404 on `/api/agents/status` (route not mounted)

- [ ] **Step 3: Write the router**

```python
# backend/routers/agent_status.py
"""Read-only status feed for the dashboard's Agent Office."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter

from .. import agent_activity
from ..monitoring_scheduler import list_monitoring_runs, parse_datetime

router = APIRouter()


def _next_run(runs: list[dict[str, Any]], interval_hours: int) -> str | None:
    """Most recent completed run + interval = the next scheduled run."""
    for run in runs:
        if run.get("status") == "completed" and run.get("finishedAt"):
            finished = parse_datetime(str(run["finishedAt"]))
            if finished:
                return (finished + timedelta(hours=interval_hours)).isoformat()
    return None


@router.get("/api/agents/status")
def agents_status() -> dict[str, Any]:
    from ..opportunity_finder import list_opportunity_runs

    live = agent_activity.live_state()
    stored = agent_activity.stored()
    last_active = stored["lastActive"]
    now = datetime.now(timezone.utc)

    next_runs: dict[str, str | None] = {
        "monitor": _next_run(list_monitoring_runs(), 4),
        "planner": _next_run(list_opportunity_runs(), 24),
    }

    agents: list[dict[str, Any]] = []
    for agent_id, name in agent_activity.AGENTS.items():
        last = last_active.get(agent_id) or {}
        entry = live.get(agent_id)
        if entry:
            started = parse_datetime(str(entry.get("startedAt") or ""))
            since = int((now - started).total_seconds()) if started else None
            agents.append(
                {
                    "id": agent_id,
                    "name": name,
                    "state": "working",
                    "activity": entry.get("activity"),
                    "sinceSeconds": max(since, 0) if since is not None else None,
                    "nextRunAt": None,
                    "lastActivity": last.get("summary"),
                    "lastActiveAt": last.get("at"),
                }
            )
            continue
        next_run = next_runs.get(agent_id)
        agents.append(
            {
                "id": agent_id,
                "name": name,
                "state": "scheduled" if next_run else "idle",
                "activity": None,
                "sinceSeconds": None,
                "nextRunAt": next_run,
                "lastActivity": last.get("summary"),
                "lastActiveAt": last.get("at"),
            }
        )

    return {"agents": agents, "events": stored["events"][:20], "updatedAt": now.isoformat()}
```

Note: `parse_datetime` lives at `backend/monitoring_scheduler.py:99` and returns a tz-aware
datetime or None (run timestamps are written with `datetime.now(timezone.utc).isoformat()`).
If `now - started` raises on a naive datetime, normalize inside `_next_run`/since with
`started.replace(tzinfo=timezone.utc)` when `started.tzinfo is None`.

- [ ] **Step 4: Mount the router in `backend/app.py`**

Add to the router imports block (next to the existing `from .routers import ... members as members_router` style imports):

```python
from .routers import agent_status as agent_status_router
```

Add `agent_status_router,` to the `for module in (...)` include loop at app.py:194–211 (after `members_router`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_agent_status_api.py backend/test_agent_activity.py -v`
Expected: all PASS. (Path note: `/api/agents/status` does not collide with the existing `GET /api/agents` in `routers/agents.py:120`.)

- [ ] **Step 6: Commit**

```bash
git add backend/routers/agent_status.py backend/app.py backend/test_agent_status_api.py
git commit -m "feat: GET /api/agents/status for the Agent Office"
```

---

### Task 3: Hook real jobs into the registry

**Files:**
- Modify: `backend/app.py:50-102` (`_monitoring_loop`)
- Modify: `backend/agentic_chat.py:369-426` (`agentic_reply`)
- Modify: `backend/opportunity_finder.py:152` (creative recommendation step)

These hooks are thin wrappers around the registry verified in Task 1; no new tests beyond a syntax/regression run. An agent never glows unless a real job runs, and skipped (debounced) runs record nothing.

- [ ] **Step 1: Wrap the monitoring loop (`backend/app.py`)**

Replace the body of the `while True:` loop in `_monitoring_loop` with:

```python
    from .agent_activity import begin as agent_begin, end as agent_end

    interval = int(os.getenv("MONITORING_INTERVAL_SECONDS", "3600"))
    while True:
        try:
            agent_begin("monitor", "scanning campaigns and ad sets")
            monitoring_result = await asyncio.to_thread(
                run_scheduled_monitoring,
                build_dashboard,
                send_alert=send_telegram_message_sync,
            )
            # Heartbeat: when monitoring actually runs (its own 4h debounce, not a
            # skipped poll), push the KPI digest so the operator always gets a
            # status table — not only when a rule trips.
            ran = isinstance(monitoring_result, dict) and not monitoring_result.get("skipped")
            agent_end("monitor", "monitoring scan completed" if ran else None)
            if ran:
                agent_begin("analyst", "sending KPI digest to Telegram")
                await asyncio.to_thread(send_kpi_digest)
                agent_end("analyst", "KPI digest sent to Telegram")
        except Exception:
            agent_end("monitor")
            agent_end("analyst")
            logger.exception("Scheduled monitoring iteration failed")
        try:
            agent_begin("planner", "daily opportunity review")
            config = get_meta_config()
            opportunity_result = await run_scheduled_opportunities(
                load_knowledge_base,
                load_playbooks=load_playbooks,
                account_id=config.ad_account_id or "unconfigured_ad_account",
                send_alert=send_approval_notification,
            )
            ran = isinstance(opportunity_result, dict) and not opportunity_result.get("skipped")
            agent_end("planner", "opportunity review completed" if ran else None)
        except Exception:
            agent_end("planner")
            logger.exception("Scheduled opportunity iteration failed")
        await asyncio.sleep(interval)
```

(The `from .agent_activity import ...` line joins the existing local imports at the top of `_monitoring_loop`. Keep the original comment about the heartbeat.)

- [ ] **Step 2: Wrap the agentic chat loop (`backend/agentic_chat.py`)**

In `agentic_reply`, after the client is built successfully (after the first `except` block that returns the friendly error), add the begin and restructure the try/finally:

```python
    from .agent_activity import begin as agent_begin, end as agent_end

    agent_begin("analyst", "answering an operator question")
    done_summary: str | None = None
    try:
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
        # ... existing loop body unchanged ...
        done_summary = "answered an operator question"
        return final_text or "Done."
    except Exception:
        logger.exception("agentic_chat: tool loop failed")
        return "I hit an error working on that. Try again, or tap /menu."
    finally:
        agent_end("analyst", done_summary)
        try:
            await client.close()
        except Exception:
            pass
```

(Only additions: the import, `agent_begin(...)`, `done_summary` flag set just before the successful return, and `agent_end(...)` first in the existing `finally`.)

- [ ] **Step 3: Wrap creative recommendations (`backend/opportunity_finder.py:152`)**

Replace `creatives = build_recommended_creatives(analysis, segment_labels)` with:

```python
    from .agent_activity import begin as agent_begin, end as agent_end

    agent_begin("creative", "selecting creatives for the proposed campaign")
    try:
        creatives = build_recommended_creatives(analysis, segment_labels)
    except Exception:
        agent_end("creative")
        raise
    agent_end("creative", "creative recommendations prepared")
```

- [ ] **Step 4: Run the full backend suite (regression)**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: 522 + 11 new = 533 passed (no failures; if an existing agentic_chat test asserts on the exact `finally` behavior, adjust only if it fails).

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/agentic_chat.py backend/opportunity_finder.py
git commit -m "feat: mark real agent activity from scheduler, chat, and creative jobs"
```

---

### Task 4: Weekly budget target setting

**Files:**
- Modify: `backend/targets_store.py:23-28` (`TARGET_FIELDS`)
- Modify: `backend/routers/targets.py:28-36` (`TargetsUpdate`)
- Test: append to `backend/test_targets_store.py` if it exists, else create it

- [ ] **Step 1: Write the failing test**

```python
# append to backend/test_targets_store.py (create the file with this content if missing)
from backend.targets_store import load_targets, save_targets


def test_weekly_budget_target_round_trips(tmp_path):
    saved = save_targets({"weeklyBudgetTargetUsd": 500}, storage_dir=tmp_path)
    assert saved["weeklyBudgetTargetUsd"] == 500.0
    assert load_targets(storage_dir=tmp_path)["weeklyBudgetTargetUsd"] == 500.0


def test_weekly_budget_target_defaults_to_none(tmp_path):
    assert load_targets(storage_dir=tmp_path)["weeklyBudgetTargetUsd"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_targets_store.py -v`
Expected: FAIL — `KeyError: 'weeklyBudgetTargetUsd'`

- [ ] **Step 3: Implement**

In `backend/targets_store.py` add to `TARGET_FIELDS`:

```python
    "weeklyBudgetTargetUsd": "max",  # $ target for 7-day spend (Monitor pace KPI)
```

In `backend/routers/targets.py` add to `TargetsUpdate`:

```python
    weeklyBudgetTargetUsd: float | None = None
```

- [ ] **Step 4: Run tests**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/test_targets_store.py backend/ -q`
Expected: all PASS (the generic load/save handles the new key; check no existing targets test asserts an exact field list — if one does, add the new key to its expectation).

- [ ] **Step 5: Commit**

```bash
git add backend/targets_store.py backend/routers/targets.py backend/test_targets_store.py
git commit -m "feat: weekly budget target setting for Monitor spend pace"
```

---

### Task 5: `deriveMonitorKpis` (frontend KPI math)

**Files:**
- Create: `src/lib/monitorKpis.ts`
- Test: `src/lib/monitorKpis.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// src/lib/monitorKpis.test.ts
import { describe, expect, it } from 'vitest'
import { deriveMonitorKpis } from './monitorKpis'
import type { DailyAdMetric } from '../types/marketing'

function metric(date: string, overrides: Partial<DailyAdMetric> = {}): DailyAdMetric {
  return {
    date,
    campaignId: 'c1',
    adSetId: 'as1',
    adId: 'a1',
    creativeId: 'cr1',
    placement: 'instagram_reels' as DailyAdMetric['placement'],
    spendUsd: 10,
    impressions: 1000,
    clicks: 25,
    landingPageViews: 20,
    leads: 5,
    telegramSubscribers: 3,
    webinarAttendees: 1,
    purchases: 0,
    purchaseRevenueUsd: 0,
    ...overrides,
  }
}

const TODAY = '2026-06-11'

// 7 complete current days (06-04..06-10) + 7 previous (05-28..06-03)
function fortnight(currentSpend = 10, previousSpend = 10): DailyAdMetric[] {
  const rows: DailyAdMetric[] = []
  for (let i = 1; i <= 7; i++) rows.push(metric(`2026-06-${String(11 - i).padStart(2, '0')}`, { spendUsd: currentSpend }))
  rows.push(metric('2026-06-03', { spendUsd: previousSpend }))
  rows.push(metric('2026-06-02', { spendUsd: previousSpend }))
  rows.push(metric('2026-06-01', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-31', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-30', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-29', { spendUsd: previousSpend }))
  rows.push(metric('2026-05-28', { spendUsd: previousSpend }))
  return rows
}

describe('deriveMonitorKpis', () => {
  it('returns the five KPIs in rail order', () => {
    const kpis = deriveMonitorKpis(fortnight(), { today: TODAY })
    expect(kpis.map((k) => k.id)).toEqual(['spend', 'leads', 'cpl', 'starts', 'ctr'])
  })

  it("excludes today's partial data from totals and deltas", () => {
    const rows = [...fortnight(), metric(TODAY, { spendUsd: 9999 })]
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    expect(kpis[0].value).toBe('$70') // 7 complete days x $10, today's 9999 ignored
  })

  it('shows budget pace only when a target is configured', () => {
    const withTarget = deriveMonitorKpis(fortnight(), { today: TODAY, weeklyBudgetTargetUsd: 140 })
    expect(withTarget[0].delta).toBe('50% of weekly budget')

    const withoutTarget = deriveMonitorKpis(fortnight(), { today: TODAY })
    expect(withoutTarget[0].delta).toContain('vs prev 7d') // plain delta, no pace claim
  })

  it('words a CPL drop as improving', () => {
    // current spend 10/day, previous 20/day, same leads -> CPL halved
    const kpis = deriveMonitorKpis(fortnight(10, 20), { today: TODAY })
    const cpl = kpis.find((k) => k.id === 'cpl')!
    expect(cpl.delta).toContain('▼')
    expect(cpl.delta).toContain('improving')
    expect(cpl.tone).toBe('good')
  })

  it('reports CTR delta in points', () => {
    const rows = fortnight()
    // halve current clicks: CTR 2.5% -> 1.25%, a -1.3pt move
    for (const row of rows) if (row.date >= '2026-06-04') row.clicks = 12
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    const ctr = kpis.find((k) => k.id === 'ctr')!
    expect(ctr.delta).toContain('pt')
    expect(ctr.tone).toBe('bad')
  })

  it('handles an empty previous window without a pace claim', () => {
    const rows = fortnight().filter((r) => r.date >= '2026-06-04')
    const kpis = deriveMonitorKpis(rows, { today: TODAY })
    expect(kpis[1].delta).toBe('no prior data')
    expect(kpis[1].tone).toBe('neutral')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/lib/monitorKpis.test.ts`
Expected: FAIL — cannot resolve `./monitorKpis`

- [ ] **Step 3: Implement**

```typescript
// src/lib/monitorKpis.ts
// KPI derivation for the Monitor rail. Delta integrity rules (see spec §3.1):
// complete days only — today's partial data would show false drops every
// morning — and spend pace renders only when a weekly budget target exists.
import type { DailyAdMetric } from '../types/marketing'
import { formatCurrency } from './format'

export type MonitorTone = 'neutral' | 'good' | 'bad'

export interface MonitorKpi {
  id: 'spend' | 'leads' | 'cpl' | 'starts' | 'ctr'
  label: string
  value: string
  delta: string
  tone: MonitorTone
}

export interface MonitorKpiOptions {
  weeklyBudgetTargetUsd?: number | null
  today?: string // ISO date treated as "today" (partial; excluded). Defaults to the current date.
}

interface Totals {
  spend: number
  leads: number
  clicks: number
  impressions: number
  starts: number
}

function isoDaysAgo(today: string, days: number): string {
  const date = new Date(`${today}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

function windowTotals(metrics: DailyAdMetric[], from: string, to: string): Totals {
  const rows = metrics.filter((m) => m.date >= from && m.date <= to)
  const sum = (pick: (m: DailyAdMetric) => number) => rows.reduce((acc, m) => acc + pick(m), 0)
  return {
    spend: sum((m) => m.spendUsd),
    leads: sum((m) => m.leads),
    clicks: sum((m) => m.clicks),
    impressions: sum((m) => m.impressions),
    starts: sum((m) => m.telegramSubscribers),
  }
}

function pctDelta(current: number, previous: number): number | null {
  if (previous <= 0) return null
  return ((current - previous) / previous) * 100
}

function pctDeltaText(
  delta: number | null,
  opts: { downIsGood?: boolean; neutral?: boolean } = {},
): { delta: string; tone: MonitorTone } {
  if (delta === null) return { delta: 'no prior data', tone: 'neutral' }
  const rounded = Math.round(Math.abs(delta))
  if (rounded === 0) return { delta: 'flat vs prev 7d', tone: 'neutral' }
  const up = delta > 0
  const arrow = up ? '▲' : '▼'
  if (opts.neutral) return { delta: `${arrow} ${rounded}% vs prev 7d`, tone: 'neutral' }
  const good = opts.downIsGood ? !up : up
  const suffix = good ? (opts.downIsGood ? ' — improving' : '') : ' — watch'
  return { delta: `${arrow} ${rounded}% vs prev 7d${suffix}`, tone: good ? 'good' : 'bad' }
}

export function deriveMonitorKpis(
  metrics: DailyAdMetric[],
  options: MonitorKpiOptions = {},
): MonitorKpi[] {
  const today = options.today ?? new Date().toISOString().slice(0, 10)
  const current = windowTotals(metrics, isoDaysAgo(today, 7), isoDaysAgo(today, 1))
  const previous = windowTotals(metrics, isoDaysAgo(today, 14), isoDaysAgo(today, 8))

  // Spend: pace vs budget only when a target is configured; never invent a pace claim.
  const target = options.weeklyBudgetTargetUsd
  let spendDelta: { delta: string; tone: MonitorTone }
  if (target && target > 0) {
    const pct = Math.round((current.spend / target) * 100)
    spendDelta = { delta: `${pct}% of weekly budget`, tone: pct > 105 ? 'bad' : 'neutral' }
  } else {
    spendDelta = pctDeltaText(pctDelta(current.spend, previous.spend), { neutral: true })
  }

  const leadsDelta = pctDeltaText(pctDelta(current.leads, previous.leads))
  const startsDelta = pctDeltaText(pctDelta(current.starts, previous.starts))

  const cplNow = current.leads > 0 ? current.spend / current.leads : null
  const cplPrev = previous.leads > 0 ? previous.spend / previous.leads : null
  const cplDelta =
    cplNow !== null && cplPrev !== null
      ? pctDeltaText(pctDelta(cplNow, cplPrev), { downIsGood: true })
      : { delta: 'no prior data' as const, tone: 'neutral' as const }

  const ctrNow = current.impressions > 0 ? (current.clicks / current.impressions) * 100 : null
  const ctrPrev = previous.impressions > 0 ? (previous.clicks / previous.impressions) * 100 : null
  let ctrDelta: { delta: string; tone: MonitorTone } = { delta: 'no prior data', tone: 'neutral' }
  if (ctrNow !== null && ctrPrev !== null) {
    const points = ctrNow - ctrPrev
    const rounded = Math.round(Math.abs(points) * 10) / 10
    if (rounded === 0) ctrDelta = { delta: 'flat vs prev 7d', tone: 'neutral' }
    else if (points > 0) ctrDelta = { delta: `▲ ${rounded}pt vs prev 7d`, tone: 'good' }
    else ctrDelta = { delta: `▼ ${rounded}pt — watch`, tone: 'bad' }
  }

  return [
    { id: 'spend', label: 'Spend · 7d', value: formatCurrency(current.spend), ...spendDelta },
    { id: 'leads', label: 'Leads', value: String(current.leads), ...leadsDelta },
    {
      id: 'cpl',
      label: 'Cost / Lead',
      value: cplNow !== null ? formatCurrency(cplNow) : '—',
      ...cplDelta,
    },
    { id: 'starts', label: 'Telegram STARTs', value: String(current.starts), ...startsDelta },
    {
      id: 'ctr',
      label: 'CTR',
      value: ctrNow !== null ? `${Math.round(ctrNow * 10) / 10}%` : '—',
      ...ctrDelta,
    },
  ]
}
```

Note: check `formatCurrency` in `src/lib/format.ts` — if it renders `$70.00` rather than `$70`, adjust the test expectation in Step 1 to the actual house format (do not change `format.ts`).

- [ ] **Step 4: Run tests**

Run: `npm test -- --run src/lib/monitorKpis.test.ts`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/monitorKpis.ts src/lib/monitorKpis.test.ts
git commit -m "feat: monitor KPI derivation with complete-days deltas"
```

---

### Task 6: Agent status provider (frontend service)

**Files:**
- Create: `src/services/agentStatusProvider.ts`
- Test: `src/services/agentStatusProvider.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// src/services/agentStatusProvider.test.ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAgentStatus } from './agentStatusProvider'

const payload = {
  agents: [
    {
      id: 'monitor',
      name: 'Monitor',
      state: 'working',
      activity: 'scanning ad sets',
      sinceSeconds: 120,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
  ],
  events: [{ agentId: 'monitor', summary: 'scan done', at: '2026-06-11T10:41:00Z' }],
  updatedAt: '2026-06-11T10:43:00Z',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getAgentStatus', () => {
  it('fetches and returns the status payload', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) } as Response)),
    )
    const result = await getAgentStatus()
    expect(result.agents[0].state).toBe('working')
    expect(result.events.length).toBe(1)
  })

  it('throws on a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 500 } as Response)))
    await expect(getAgentStatus()).rejects.toThrow()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/services/agentStatusProvider.test.ts`
Expected: FAIL — cannot resolve `./agentStatusProvider`

- [ ] **Step 3: Implement**

```typescript
// src/services/agentStatusProvider.ts
export type AgentState = 'working' | 'idle' | 'scheduled'

export interface AgentStatus {
  id: string
  name: string
  state: AgentState
  activity: string | null
  sinceSeconds: number | null
  nextRunAt: string | null
  lastActivity: string | null
  lastActiveAt: string | null
}

export interface AgentEvent {
  agentId: string
  summary: string
  at: string
}

export interface AgentStatusPayload {
  agents: AgentStatus[]
  events: AgentEvent[]
  updatedAt: string
}

export async function getAgentStatus(): Promise<AgentStatusPayload> {
  const response = await fetch('/api/agents/status')
  if (!response.ok) {
    throw new Error(`Agent status request failed: ${response.status}`)
  }
  return (await response.json()) as AgentStatusPayload
}
```

- [ ] **Step 4: Run tests**

Run: `npm test -- --run src/services/agentStatusProvider.test.ts`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/agentStatusProvider.ts src/services/agentStatusProvider.test.ts
git commit -m "feat: agent status provider"
```

---

### Task 7: AgentOffice component

**Files:**
- Create: `src/components/dashboard/views/AgentOffice.tsx`
- Test: `src/components/dashboard/views/AgentOffice.test.tsx`

- [ ] **Step 1: Write the failing tests**

```typescript
// src/components/dashboard/views/AgentOffice.test.tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { AgentOffice } from './AgentOffice'
import type { AgentStatusPayload } from '../../../services/agentStatusProvider'

const payload: AgentStatusPayload = {
  agents: [
    {
      id: 'monitor',
      name: 'Monitor',
      state: 'working',
      activity: 'scanning 14 ad sets',
      sinceSeconds: 120,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
    {
      id: 'analyst',
      name: 'Analyst',
      state: 'idle',
      activity: null,
      sinceSeconds: null,
      nextRunAt: null,
      lastActivity: 'KPI digest sent to Telegram',
      lastActiveAt: '2026-06-11T08:41:00Z',
    },
    {
      id: 'planner',
      name: 'Planner',
      state: 'scheduled',
      activity: null,
      sinceSeconds: null,
      nextRunAt: '2026-06-11T14:00:00Z',
      lastActivity: 'opportunity review completed',
      lastActiveAt: '2026-06-10T14:00:00Z',
    },
    {
      id: 'creative',
      name: 'Creative',
      state: 'idle',
      activity: null,
      sinceSeconds: null,
      nextRunAt: null,
      lastActivity: null,
      lastActiveAt: null,
    },
  ],
  events: [
    { agentId: 'monitor', summary: 'scan done — 14 ad sets healthy', at: '2026-06-11T10:41:00Z' },
    { agentId: 'analyst', summary: 'KPI digest sent to Telegram', at: '2026-06-11T08:41:00Z' },
  ],
  updatedAt: '2026-06-11T10:43:00Z',
}

function stubFetch(data: AgentStatusPayload | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      data
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(data) } as Response)
        : Promise.reject(new Error('offline')),
    ),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AgentOffice', () => {
  it('summarizes working vs idle and shows activity sentences', async () => {
    stubFetch(payload)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/1 working · 3 idle/)).toBeTruthy()
    })
    expect(screen.getByText(/working — scanning 14 ad sets/)).toBeTruthy()
    // Idle agent shows its last real activity, not a bare "idle"
    expect(screen.getByText(/last: KPI digest sent to Telegram/)).toBeTruthy()
  })

  it('renders the recent activity feed', async () => {
    stubFetch(payload)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/scan done — 14 ad sets healthy/)).toBeTruthy()
    })
  })

  it('marks working agents in the office scene', async () => {
    stubFetch(payload)
    const { container } = render(<AgentOffice />)
    await waitFor(() => {
      expect(container.querySelector('.office-desk.working')).toBeTruthy()
    })
    expect(container.querySelectorAll('.office-desk').length).toBe(4)
  })

  it('shows a connecting state before data arrives and survives fetch failure', async () => {
    stubFetch(null)
    render(<AgentOffice />)
    await waitFor(() => {
      expect(screen.getByText(/unavailable/i)).toBeTruthy()
    })
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/components/dashboard/views/AgentOffice.test.tsx`
Expected: FAIL — cannot resolve `./AgentOffice`

- [ ] **Step 3: Implement**

```tsx
// src/components/dashboard/views/AgentOffice.tsx
import { useEffect, useRef, useState } from 'react'
import {
  getAgentStatus,
  type AgentStatus,
  type AgentStatusPayload,
} from '../../../services/agentStatusProvider'

const AGENT_ICONS: Record<string, string> = {
  monitor: '🛰️',
  analyst: '📊',
  planner: '🧭',
  creative: '🎨',
}

const DESK_POSITIONS: Record<string, { left: string; top: string }> = {
  monitor: { left: '16%', top: '12%' },
  analyst: { left: '62%', top: '12%' },
  planner: { left: '14%', top: '56%' },
  creative: { left: '64%', top: '56%' },
}

// Working agents "walk" to the center table; the move is a CSS transition on
// left/top (spec §3.3 — walk plays on state change between polls).
const TABLE_POSITIONS: Record<string, { left: string; top: string }> = {
  monitor: { left: '30%', top: '26%' },
  analyst: { left: '52%', top: '26%' },
  planner: { left: '30%', top: '46%' },
  creative: { left: '52%', top: '46%' },
}

function formatElapsed(seconds: number | null): string {
  if (seconds === null) return ''
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function relativeTime(iso: string | null): string {
  if (!iso) return ''
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function statusSentence(agent: AgentStatus): string {
  if (agent.state === 'working') {
    const elapsed = formatElapsed(agent.sinceSeconds)
    return `working — ${agent.activity ?? '…'}${elapsed ? ` · ${elapsed}` : ''}`
  }
  const last = agent.lastActivity
    ? `last: ${agent.lastActivity}, ${relativeTime(agent.lastActiveAt)}`
    : 'no recent activity'
  if (agent.state === 'scheduled' && agent.nextRunAt) {
    return `${last} · next ${formatClock(agent.nextRunAt)}`
  }
  return last
}

export function AgentOffice({ pollMs = 30000 }: { pollMs?: number }) {
  const [payload, setPayload] = useState<AgentStatusPayload | null>(null)
  const [failed, setFailed] = useState(false)
  const staleRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const next = await getAgentStatus()
        if (!cancelled) {
          setPayload(next)
          setFailed(false)
          staleRef.current = false
        }
      } catch {
        if (!cancelled) {
          staleRef.current = true
          setFailed(true) // keeps last payload if any; shows unavailable otherwise
        }
      }
    }
    void load()
    const id = setInterval(() => void load(), pollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollMs])

  if (!payload) {
    return (
      <section className="monitor-office" aria-label="Agent Office">
        <div className="office-heading">
          <h5>Agent Office</h5>
        </div>
        <p className="office-empty">{failed ? 'Agent status unavailable' : 'Connecting…'}</p>
      </section>
    )
  }

  const working = payload.agents.filter((agent) => agent.state === 'working').length
  const idle = payload.agents.length - working
  const summary = `${working} working · ${idle} idle${failed ? ' · stale' : ''}`

  return (
    <section className="monitor-office" aria-label="Agent Office">
      <div className="office-heading">
        <h5>Agent Office</h5>
        <small>{summary}</small>
      </div>

      <div className="office-scene" aria-hidden="true">
        <div className="office-table" />
        {payload.agents.map((agent) => (
          <div
            key={agent.id}
            className={`office-desk ${agent.state === 'working' ? 'working' : 'resting'}`}
            style={agent.state === 'working' ? TABLE_POSITIONS[agent.id] : DESK_POSITIONS[agent.id]}
          >
            <span className="office-face">
              {AGENT_ICONS[agent.id] ?? '🤖'}
              <i />
            </span>
            <span className="office-name">{agent.name}</span>
          </div>
        ))}
      </div>

      <div className="office-strip" aria-hidden="true">
        {payload.agents.map((agent) => (
          <span
            key={agent.id}
            className={`strip-agent ${agent.state === 'working' ? 'working' : 'resting'}`}
          >
            {AGENT_ICONS[agent.id] ?? '🤖'}
            <i />
          </span>
        ))}
        <small>{summary}</small>
      </div>

      <ul className="office-list">
        {payload.agents.map((agent) => (
          <li key={agent.id} className={agent.state === 'working' ? 'working' : 'resting'}>
            <span className="office-mini">{AGENT_ICONS[agent.id] ?? '🤖'}</span>
            <div>
              <strong>{agent.name}</strong>
              <span>{statusSentence(agent)}</span>
            </div>
          </li>
        ))}
      </ul>

      {payload.events.length > 0 && (
        <div className="office-feed">
          <h6>Recent activity</h6>
          <ul>
            {payload.events.slice(0, 5).map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <time>{formatClock(event.at)}</time>
                <span>
                  <b>{payload.agents.find((a) => a.id === event.agentId)?.name ?? event.agentId}</b>{' '}
                  — {event.summary}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `npm test -- --run src/components/dashboard/views/AgentOffice.test.tsx`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/dashboard/views/AgentOffice.tsx src/components/dashboard/views/AgentOffice.test.tsx
git commit -m "feat: AgentOffice component with live scene, status list, and feed"
```

---

### Task 8: MonitorView component

**Files:**
- Create: `src/components/dashboard/views/MonitorView.tsx`
- Test: `src/components/dashboard/views/MonitorView.test.tsx`

- [ ] **Step 1: Write the failing tests**

```typescript
// src/components/dashboard/views/MonitorView.test.tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MonitorView } from './MonitorView'
import type { DailyAdMetric, FunnelSummary, TrendPoint } from '../../../types/marketing'

const funnel: FunnelSummary[] = [
  { step: 'Ad impressions', value: 128400, rate: '100%' },
  { step: 'Clicks', value: 3082, rate: '2.4%' },
  { step: 'Landing visits', value: 2100, rate: '68.1%' },
  { step: 'Leads', value: 312, rate: '14.9%' },
  { step: 'Telegram subs', value: 208, rate: '66.7%' },
  { step: 'Webinar attendees', value: 96, rate: '46.2%' },
  { step: 'Buyers', value: 0, rate: '0%' },
]

const trend: TrendPoint[] = [
  { day: '2026-06-09', spend: 170, leads: 44, buyers: 0 },
  { day: '2026-06-10', spend: 181, leads: 47, buyers: 0 },
]

const metrics: DailyAdMetric[] = []

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/targets')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ targets: { weeklyBudgetTargetUsd: 200 } }),
        } as Response)
      }
      if (url.includes('/api/agents/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ agents: [], events: [], updatedAt: '' }),
        } as Response)
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)
    }),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('MonitorView', () => {
  it('renders the five KPI labels in rail order', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText('Cost / Lead')).toBeTruthy())
    expect(screen.getByText('Spend · 7d')).toBeTruthy()
    expect(screen.getByText('Telegram STARTs')).toBeTruthy()
    expect(screen.getByText('CTR')).toBeTruthy()
  })

  it('renders the five funnel stages with CTR on the clicks row, skipping visits and buyers', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText(/Clicks · CTR 2.4%/)).toBeTruthy())
    expect(screen.getByText('Ad impressions')).toBeTruthy()
    expect(screen.getByText('Webinar attended')).toBeTruthy()
    expect(screen.queryByText('Landing visits')).toBeNull()
    expect(screen.queryByText('Buyers')).toBeNull()
  })

  it('renders the Agent Office panel', async () => {
    stubFetch()
    render(<MonitorView metrics={metrics} trend={trend} funnel={funnel} />)
    await waitFor(() => expect(screen.getByText('Agent Office')).toBeTruthy())
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- --run src/components/dashboard/views/MonitorView.test.tsx`
Expected: FAIL — cannot resolve `./MonitorView`

- [ ] **Step 3: Implement**

```tsx
// src/components/dashboard/views/MonitorView.tsx
// The lean Monitor screen: KPI rail / one trend + funnel / Agent Office.
// Monitoring only — control lives in Telegram and the Claude connector.
import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from 'recharts'
import { deriveMonitorKpis } from '../../../lib/monitorKpis'
import { chartTooltipFormatter, formatAxisCurrency } from '../../../lib/chartConfig'
import type { DailyAdMetric, FunnelSummary, TrendPoint } from '../../../types/marketing'
import { ChartFrame } from '../shared/ChartFrame'
import { AgentOffice } from './AgentOffice'

// Spec §3.2: five stages; landing visits and buyers are intentionally omitted
// (buyers return when purchase tracking is activated).
const STAGE_LABELS: Array<{ step: string; label: (stage: FunnelSummary) => string }> = [
  { step: 'Ad impressions', label: () => 'Ad impressions' },
  { step: 'Clicks', label: (stage) => `Clicks · CTR ${stage.rate}` },
  { step: 'Leads', label: () => 'Leads' },
  { step: 'Telegram subs', label: () => 'Telegram STARTs' },
  { step: 'Webinar attendees', label: () => 'Webinar attended' },
]

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

interface MonitorViewProps {
  metrics: DailyAdMetric[]
  trend: TrendPoint[]
  funnel: FunnelSummary[]
}

export function MonitorView({ metrics, trend, funnel }: MonitorViewProps) {
  const [budgetTarget, setBudgetTarget] = useState<number | null>(null)

  useEffect(() => {
    if (typeof fetch !== 'function') return
    void fetch('/api/targets')
      .then((response) => (response.ok ? response.json() : { targets: null }))
      .then((result: { targets?: Record<string, number | null> }) => {
        setBudgetTarget(result.targets?.weeklyBudgetTargetUsd ?? null)
      })
      .catch(() => undefined)
  }, [])

  const kpis = useMemo(
    () => deriveMonitorKpis(metrics, { weeklyBudgetTargetUsd: budgetTarget }),
    [metrics, budgetTarget],
  )

  const stages = STAGE_LABELS.map(({ step, label }) => {
    const stage = funnel.find((item) => item.step === step)
    return stage ? { label: label(stage), value: stage.value } : null
  }).filter((stage): stage is { label: string; value: number } => stage !== null)
  const stageMax = stages[0]?.value || 1

  const recentTrend = trend.slice(-14)

  // Collapsed by default on phones (spec §3.4); <details open> can't be CSS-driven.
  const [chartsOpen] = useState(
    () => typeof window === 'undefined' || window.innerWidth > 768,
  )

  return (
    <section className="monitor-screen">
      <div className="monitor-kpis" aria-label="Key metrics">
        {kpis.map((kpi) => (
          <div key={kpi.id} className="monitor-kpi">
            <small>{kpi.label}</small>
            <strong>{kpi.value}</strong>
            <span className={`monitor-delta ${kpi.tone}`}>{kpi.delta}</span>
          </div>
        ))}
      </div>

      <details className="monitor-center" open={chartsOpen}>
        <summary>Trend &amp; funnel</summary>
        <div className="monitor-trend">
          <h5>Spend &amp; leads · last 14 days</h5>
          <ChartFrame summary="Daily spend and leads for the last 14 days">
            <LineChart data={recentTrend}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="spend" tickFormatter={formatAxisCurrency} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="leads" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={chartTooltipFormatter} />
              <Legend />
              <Line yAxisId="spend" type="monotone" dataKey="spend" stroke="var(--chart-1)" strokeWidth={2.5} dot={false} />
              <Line yAxisId="leads" type="monotone" dataKey="leads" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
            </LineChart>
          </ChartFrame>
        </div>
        <div className="monitor-funnel">
          <h5>Funnel · 7 days</h5>
          {stages.map((stage) => (
            <div key={stage.label} className="monitor-funnel-row">
              <span>{stage.label}</span>
              <div className="bar-track">
                <div className="bar" style={{ width: `${Math.max((stage.value / stageMax) * 100, 1)}%` }} />
              </div>
              <b>{compact.format(stage.value)}</b>
            </div>
          ))}
        </div>
      </details>

      <AgentOffice />
    </section>
  )
}
```

Note: check `src/lib/chartConfig.ts` export names (`formatAxisCurrency`, `chartTooltipFormatter`) before importing — use the actual exported identifiers.

- [ ] **Step 4: Run tests**

Run: `npm test -- --run src/components/dashboard/views/MonitorView.test.tsx`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/dashboard/views/MonitorView.tsx src/components/dashboard/views/MonitorView.test.tsx
git commit -m "feat: MonitorView — single-screen KPI rail, trend, funnel, agent office"
```

---

### Task 9: Rewire Dashboard.tsx and delete dead web UI

**Files:**
- Modify: `src/components/Dashboard.tsx` (1,625 lines — major surgery)
- Rewrite: `src/components/Dashboard.test.tsx`
- Delete: `src/services/agentChatProvider.ts`, `src/services/agentTaskProvider.ts`, `src/services/agentTaskProvider.test.ts`, `src/lib/operatorAttention.ts`, `src/lib/operatorAttention.test.ts`

Backend chat/approval APIs are untouched — Telegram and the MCP connector use them. Only the web UI surface goes.

- [ ] **Step 1: Write the failing nav test (rewrite `Dashboard.test.tsx`)**

Replace the entire file (its current tests cover the ApprovalQueue, which is being deleted):

```typescript
// src/components/Dashboard.test.tsx
import { describe, expect, it } from 'vitest'
import { visibleNavFor } from './Dashboard'

describe('visibleNavFor', () => {
  it('has no chat tab for anyone — control lives in Telegram', () => {
    for (const role of [null, 'owner', 'admin', 'viewer']) {
      expect(visibleNavFor(role).map((item) => item.id)).not.toContain('chat')
    }
  })

  it('shows monitor, rankings, settings to viewers', () => {
    expect(visibleNavFor('viewer').map((item) => item.id)).toEqual([
      'overview',
      'rankings',
      'settings',
    ])
  })

  it('adds team for managers and defaults (dev mode)', () => {
    expect(visibleNavFor('admin').map((item) => item.id)).toContain('team')
    expect(visibleNavFor(null).map((item) => item.id)).toContain('team')
  })
})
```

Run: `npm test -- --run src/components/Dashboard.test.tsx`
Expected: FAIL — `visibleNavFor` is not exported

- [ ] **Step 2: Edit `Dashboard.tsx` — nav, default view, helper**

1. Remove the chat entry from `navItems` (line ~97) and export the helper:

```typescript
const navItems = [
  { id: 'overview', label: 'Monitor', icon: LayoutDashboard },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
  { id: 'team', label: 'Team', icon: Users, managerOnly: true },
] as const

export function visibleNavFor(role: string | null) {
  const isManager = role === null || role === 'owner' || role === 'admin'
  return navItems.filter((item) => !('managerOnly' in item && item.managerOnly) || isManager)
}
```

(Keep the existing `isManager` gating semantics exactly — `null` role = dev mode = full access. Replace the inline `visibleNavItems` computation with `const visibleNavItems = visibleNavFor(role)`.)

2. Default view (line ~147): change `useState<ViewId>(isManager ? 'chat' : 'overview')` to `useState<ViewId>('overview')`.

3. Filters bar: change `{activeView !== 'chat' && <Filters ... />}` to `<Filters data={data} filters={filters} onChange={setFilters} />`.

- [ ] **Step 3: Edit `Dashboard.tsx` — delete dead components and state**

Delete (current line ranges; they shift as you cut — search by symbol name):
- Chat view conditional render (lines ~311–321)
- `CHAT_STARTER_PROMPTS` (~564–569), `CampaignChatView` (~571–704), `AgentChatPanel` (~706–803)
- Chat state + handlers: `chatMessages`/`chatInput`/`isChatLoading` state (~149–158), `sendChatMessage`/`askAgentsAbout` (~199–245), the metaStatus useEffect if only chat used it
- `DecisionHero` (~957–1007), `TopProblemsPanel` (~932–955), `InsightsPanel` (~1151–1171)
- `ApprovalQueue` (~1297–1549) and its render sites
- `KpiGrid` (~859–880), `FunnelPanel` (~882–908), `TrendPanel` (~910–930), `SpendPanel` (~1119–1136)
- `CreativeTablePanel`/`CreativeTable` (~1009–1059), `PlacementPanel` (~1061–1082), `AudiencePanel` (~1097–1117)
- `deriveFilteredKpis` + `toneForRate` (~1562–1624)
- The old `Overview` component (~805–857)
- Now-unused imports: `Send` icon, `askAgent`, `getAgentCommandCenter`, `buildOperatorAttention`, recharts imports no longer used in this file, etc. (let `npm run lint` find stragglers)

- [ ] **Step 4: Edit `Dashboard.tsx` — render MonitorView + freshness stamp**

1. Import the new view: `import { MonitorView } from './dashboard/views/MonitorView'`

2. Replace the old Overview render branch (~327–341) with:

```tsx
{activeView === 'overview' &&
  (hasData ? (
    <MonitorView metrics={filteredMetrics} trend={trend} funnel={funnel} />
  ) : (
    <EmptyState onReset={() => setFilters(defaultFilters)} />
  ))}
```

(`filteredMetrics`, `trend`, `funnel` are the existing `useMemo` values that fed the old Overview — keep those memos; delete any memos only the deleted panels used, e.g. `creativeScores`/`placements` if Rankings doesn't take them as props — check `RankingsView` usage first. The `EmptyState onReset` handler is verbatim from the current branch. **Keep the `metaStatus` state + effect** — `SettingsView` receives `metaStatus={metaStatus}`; only delete it if your grep shows chat was its sole consumer, which it is not.)

3. Freshness stamp (spec §3.1) — add inside the Dashboard component:

```tsx
const [loadedAt, setLoadedAt] = useState<Date>(() => new Date())
useEffect(() => {
  setLoadedAt(new Date())
}, [data])
const isLive = data.dataSource?.kind === 'meta' && !data.dataSource?.backendUnreachable
const freshness = `${isLive ? 'data as of' : 'snapshot ·'} ${loadedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
```

And in the topbar actions (next to the existing dataSource pill, ~line 268):

```tsx
<div className="status-pill neutral">{freshness}</div>
```

- [ ] **Step 5: Delete the orphaned files**

```bash
git rm src/services/agentChatProvider.ts src/services/agentTaskProvider.ts src/services/agentTaskProvider.test.ts src/lib/operatorAttention.ts src/lib/operatorAttention.test.ts
```

(If `operatorAttention` is still imported anywhere — grep first: `grep -rn "operatorAttention\|buildOperatorAttention" src/` — it should only have been the deleted DecisionHero/TopProblemsPanel.)

- [ ] **Step 6: Verify nothing dangles**

```bash
grep -rn "ApprovalQueue\|DecisionHero\|TopProblemsPanel\|InsightsPanel\|SpendPanel\|KpiGrid\|CampaignChatView\|AgentChatPanel\|deriveFilteredKpis\|askAgent\|getAgentCommandCenter\|CHAT_STARTER_PROMPTS" src/
```
Expected: no matches.

Run: `npm test -- --run` and `npm run lint`
Expected: all tests pass (including the new `visibleNavFor` tests), lint clean. Fix any unused-import errors lint surfaces.

- [ ] **Step 7: Commit**

```bash
git add -A src/
git commit -m "refactor: lean monitor — remove web chat/approvals/hero panels, wire MonitorView"
```

---

### Task 10: CSS — monitor styles in, dead styles out

**Files:**
- Modify: `src/App.css`

- [ ] **Step 1: Add the new monitor styles**

Append a new section to `App.css` (uses existing tokens from `index.css`):

```css
/* ===== Lean Monitor (single-screen) ===== */
.monitor-screen {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.monitor-kpis { display: flex; flex-direction: column; gap: 14px; }
.monitor-kpi {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: grid;
  gap: 2px;
}
.monitor-kpi small {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.monitor-kpi strong { font-size: 24px; font-weight: var(--weight-strong); }
.monitor-delta { font-size: 12px; color: var(--text-muted); }
.monitor-delta.good { color: var(--accent); }
.monitor-delta.bad { color: #b4543e; }

.monitor-center {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.monitor-center > summary {
  cursor: pointer;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  list-style: none;
}
.monitor-center h5 {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 14px 0 8px;
}
.monitor-funnel-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) 56px;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 7px;
}
.monitor-funnel-row .bar-track { background: var(--surface-muted); border-radius: 4px; height: 12px; }
.monitor-funnel-row .bar { background: var(--accent-drift); border-radius: 4px; height: 100%; }
.monitor-funnel-row b { text-align: right; color: var(--text); }

/* Agent Office panel */
.monitor-office {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.office-heading { display: flex; justify-content: space-between; align-items: baseline; }
.office-heading h5 {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 0;
}
.office-heading small { font-size: 11px; color: var(--text-muted); }
.office-empty { color: var(--text-muted); font-size: 13px; }

.office-scene {
  position: relative;
  height: 200px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: radial-gradient(ellipse at 50% 35%, var(--accent-soft) 0%, var(--surface-muted) 100%);
  overflow: hidden;
}
.office-table {
  position: absolute;
  left: 50%;
  top: 46%;
  transform: translate(-50%, -50%);
  width: 34%;
  height: 24%;
  border-radius: 50%;
  background: var(--border);
  opacity: 0.8;
}
.office-desk {
  position: absolute;
  width: 56px;
  text-align: center;
  /* the "walk": working agents move from desk to table on state change */
  transition: left 2.2s ease-in-out, top 2.2s ease-in-out;
}
.office-desk .office-face {
  width: 34px;
  height: 34px;
  margin: 0 auto;
  border-radius: 50%;
  background: var(--surface);
  border: 2px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  position: relative;
}
.office-desk .office-face i {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid var(--surface);
  background: var(--text-muted);
}
.office-desk.working .office-face { border-color: var(--accent); animation: monitorGlow 2s ease-in-out infinite; }
.office-desk.working .office-face i { background: #22c55e; }
.office-desk.resting .office-face { opacity: 0.6; }
.office-desk .office-name {
  display: block;
  margin-top: 4px;
  font-size: 10px;
  font-weight: var(--weight-medium);
  color: var(--text-muted);
}

.office-strip { display: none; align-items: center; gap: 8px; }
.office-strip .strip-agent {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--surface-muted);
  border: 2px solid var(--border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  position: relative;
}
.office-strip .strip-agent i {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid var(--surface);
  background: var(--text-muted);
}
.office-strip .strip-agent.working { border-color: var(--accent); animation: monitorBob 1.7s ease-in-out infinite; }
.office-strip .strip-agent.working i { background: #22c55e; }
.office-strip small { color: var(--text-muted); font-size: 11px; }

.office-list { list-style: none; margin: 0; padding: 0; }
.office-list li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
}
.office-list li:last-child { border-bottom: 0; }
.office-list .office-mini {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--surface-muted);
  border: 1.5px solid var(--border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
}
.office-list li.working .office-mini { border-color: var(--accent); animation: monitorBob 1.7s ease-in-out infinite; }
.office-list strong { display: block; font-size: 13px; }
.office-list li.working strong + span { color: var(--accent); }
.office-list span { font-size: 11px; color: var(--text-muted); display: block; }

.office-feed h6 {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin: 0 0 6px;
}
.office-feed ul { list-style: none; margin: 0; padding: 0; }
.office-feed li {
  display: flex;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
  padding: 4px 0;
  line-height: 1.4;
}
.office-feed time { flex-shrink: 0; color: var(--text-muted); opacity: 0.7; }
.office-feed b { color: var(--text); font-weight: var(--weight-medium); }

@keyframes monitorGlow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(31, 157, 138, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(31, 157, 138, 0); }
}
@keyframes monitorBob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

@media (max-width: 1180px) {
  .monitor-screen { grid-template-columns: 1fr; }
  .monitor-kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
}

@media (max-width: 768px) {
  /* Spec §3.4: KPI grid first, agent strip second, charts collapsed last */
  .monitor-kpis { grid-template-columns: repeat(2, 1fr); }
  .monitor-screen { display: flex; flex-direction: column; }
  .monitor-kpis { order: 1; }
  .monitor-office { order: 2; }
  .monitor-center { order: 3; }
  .office-scene { display: none; }
  .office-strip { display: flex; }
}

@media (prefers-reduced-motion: reduce) {
  .office-desk { transition: none; }
  .office-desk.working .office-face,
  .office-strip .strip-agent.working,
  .office-list li.working .office-mini { animation: none; }
}
```

- [ ] **Step 2: Delete dead style blocks**

For each block: grep its primary class names against `src/` first; delete only when there are zero remaining references.

| Block | App.css lines (pre-edit) | Key selectors to grep |
|---|---|---|
| Campaign chat view | ~147–162 | `.campaign-chat-view`, `.campaign-chat-intro`, `.campaign-chat-starters` |
| Chat shell/messages/input | ~314–461 | `.agent-chat-shell`, `.chat-message`, `.chat-suggestions`, `.chat-input-row` |
| Decision hero | ~659–751 | `.decision-hero`, `.decision-block-grid` |
| Approval UI | ~1519–1675 | `.approval-button-stack`, `.approval-guardrails`, `.approval-proactive`, `.approval-opportunity`, `.approval-after` |
| Old agent office/council | ~2633–3268 | `.agent-office-view`, `.agent-office-map`, `.agent-desk`, `.agent-circle`, `.office-center-table`, `councilPulse`, `councilLineFlow`, `agentWalk` |
| Problem/insight items | within ~932–990 | `.problem-item`, `.insight-item` — **careful**: `.problem-list` shares a grid rule with `.funnel-list`/`.insight-list`; keep any shared base rule that other surviving selectors use |

Also sweep the responsive blocks (~3271–3430) for references to deleted selectors (`.agent-office-view`, `.decision-hero`, etc.) and remove those lines.

```bash
grep -rn "decision-hero\|campaign-chat\|agent-chat\|approval-guardrails\|agent-office-map\|agent-circle" src/ --include="*.tsx" --include="*.ts"
```
Expected: no matches before deleting each block.

- [ ] **Step 3: Verify**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: tests pass, lint clean, build succeeds (the pre-existing >500 kB single-chunk warning is fine — it should shrink, not grow).

- [ ] **Step 4: Commit**

```bash
git add src/App.css
git commit -m "style: monitor screen styles; remove dead chat/approval/hero/office CSS"
```

---

### Task 11: Weekly budget target in Settings

**Files:**
- Modify: `src/components/dashboard/views/SettingsView.tsx:393-398` (`TARGET_FIELDS`)

- [ ] **Step 1: Add the field**

The targets form renders from the `TARGET_FIELDS` array — one addition covers JSX, load, and save:

```typescript
const TARGET_FIELDS = [
  { key: 'maxCpl', label: 'Max cost per lead ($)', hint: 'Flag when CPL rises above this' },
  { key: 'minLeadRate', label: 'Min lead rate (%)', hint: 'Leads / clicks floor' },
  { key: 'maxCostPerStart', label: 'Max cost per Telegram START ($)', hint: 'Spend / START ceiling' },
  { key: 'minStartRate', label: 'Min START rate (%)', hint: 'START-rate floor' },
  { key: 'weeklyBudgetTargetUsd', label: 'Weekly budget target ($)', hint: 'Monitor shows spend pace against this' },
] as const
```

- [ ] **Step 2: Verify**

Run: `npm test -- --run && npm run lint`
Expected: pass. (Backend round-trip already covered by Task 4's test; the form machinery is generic.)

- [ ] **Step 3: Commit**

```bash
git add src/components/dashboard/views/SettingsView.tsx
git commit -m "feat: weekly budget target field in Settings"
```

---

### Task 12: Full verification

- [ ] **Step 1: Full backend suite**

Run: `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
Expected: 0 failures (baseline 522 + ~13 new).

- [ ] **Step 2: Full frontend suite + lint + build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: 0 failures (old ApprovalQueue tests were replaced in Task 9), lint clean, build succeeds.

- [ ] **Step 3: Visual smoke (optional but recommended)**

Start the backend locally (`python -m uvicorn backend.app:app --port 8000`) and `npm run dev`; check: Monitor is the default view, no Chat tab, KPI rail renders, Agent Office shows idle agents with last-activity lines, narrow window switches to the mobile layout.

- [ ] **Step 4: Final commit & wrap-up**

```bash
git add -A
git commit -m "feat: lean monitor dashboard (spec 2026-06-11)"
```

Deployment is explicitly OUT of this plan — production restart requires separate operator authorization (HANDOFF §3).

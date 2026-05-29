# Meta Agent Completion Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Meta Ad Agent from an analysis dashboard into an approval-safe operating system that can analyze, plan, monitor, request approval, and execute approved Meta Ads actions.

**Architecture:** Each phase ships as a small, testable slice with one production capability and one verification gate. Natural-language requests enter through dashboard, Telegram, or Codex chat, pass through the Orchestrator, become structured tasks/approval requests, and only execute after explicit approval. Execution uses Meta API first and browser fallback only for approved actions that cannot be done through the API.

**Tech Stack:** FastAPI backend, Vite/React dashboard, pytest backend tests, Vitest frontend tests, Meta Marketing API, Telegram Bot API, local JSON storage now, database-ready interfaces later.

---

## Completion Order

Build in this order and do not move to the next phase until the current phase passes automated tests, API/manual verification, and commit review:

1. Version 0.4: Approved Meta execution for simple actions.
2. Version 0.5: Four-hour monitoring and alert loop.
3. Version 0.6: Funnel tracking completion for visitor, landing click, Telegram START, bot steps, and CRM/Sheet import.
4. Version 0.7: Creative Intelligence with thumbnails, video playback, and ranking.
5. Version 0.8: Knowledge base automation and 180-day strategy refresh.
6. Version 0.9: Dashboard Command Center polish and agent health visualization.

---

## Phase 0: Preflight Gate

**Purpose:** Make sure the branch is clean and current before each phase.

**Files:**
- Read: `backend/app.py`
- Read: `backend/meta_execution.py`
- Read: `backend/meta_action_planner.py`
- Read: `backend/agent_orchestrator.py`
- Read: `docs/AGENT_OPERATING_POLICY.md`

- [ ] **Step 1: Check worktree**

Run:

```powershell
git status --short
git branch --show-current
```

Expected:

```text
codex/meta-agent
```

No unrelated modified files. If unrelated files exist, do not touch them.

- [ ] **Step 2: Run baseline tests**

Run:

```powershell
python -m pytest backend -q
npm test -- --run
npm run build
```

Expected:

```text
backend tests pass
frontend tests pass
vite build exits 0
```

- [ ] **Step 3: Stop gate**

Only proceed if baseline is green. If anything fails, create a failing regression test for that failure and fix it before starting the phase.

---

## Phase 1: Version 0.4 Approved Meta Execution

**Goal:** Execute approved simple Meta actions: rename, pause, enable, and budget change. No publish/spend action can happen without an approved request.

**Files:**
- Modify: `backend/meta_execution.py`
- Modify: `backend/app.py`
- Modify: `backend/approval_store.py` only if status transitions need one helper
- Test: `backend/test_meta_action_execution.py`
- Test: `backend/test_approval_execution_api.py`
- Docs: `docs/META_EXECUTION_SAFETY.md`

### Task 1.1: Add execution tests for rename, pause, enable, and budget

- [ ] **Step 1: Write failing tests**

Create `backend/test_meta_action_execution.py`:

```python
import pytest

from backend.meta_execution import execute_meta_action_approval


class FakeMetaWriter:
    def __init__(self):
        self.calls = []

    async def update_campaign(self, object_id, payload):
        self.calls.append(("campaign", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad_set(self, object_id, payload):
        self.calls.append(("adset", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad(self, object_id, payload):
        self.calls.append(("ad", object_id, payload))
        return {"success": True, "id": object_id, **payload}


@pytest.mark.asyncio
async def test_execute_approved_campaign_rename():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_rename",
        "status": "approved",
        "actionType": "rename_meta_object",
        "target": {"level": "campaign", "id": "120123"},
        "after": {"name": "Business Automation VSL - Tashkent"},
    }

    result = await execute_meta_action_approval(approval, writer=writer)

    assert result["ok"] is True
    assert writer.calls == [("campaign", "120123", {"name": "Business Automation VSL - Tashkent"})]


@pytest.mark.asyncio
async def test_execute_approved_adset_budget_change_converts_usd_to_meta_minor_units():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_budget",
        "status": "approved",
        "actionType": "change_meta_budget",
        "target": {"level": "adset", "id": "9988"},
        "after": {"daily_budget_usd": 120},
    }

    result = await execute_meta_action_approval(approval, writer=writer)

    assert result["ok"] is True
    assert writer.calls == [("adset", "9988", {"daily_budget": 12000})]


@pytest.mark.asyncio
async def test_execute_rejects_unapproved_request():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_unapproved",
        "status": "needs_review",
        "actionType": "pause_meta_object",
        "target": {"level": "campaign", "id": "120123"},
        "after": {"status": "PAUSED"},
    }

    result = await execute_meta_action_approval(approval, writer=writer)

    assert result["ok"] is False
    assert result["blockedReason"] == "Approval must be approved before execution."
    assert writer.calls == []
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest backend\test_meta_action_execution.py -q
```

Expected: fail because `execute_meta_action_approval` does not exist.

### Task 1.2: Implement minimal Meta action executor

- [ ] **Step 1: Add executor function**

Modify `backend/meta_execution.py` and add:

```python
async def execute_meta_action_approval(approval: dict[str, Any], *, writer: Any) -> dict[str, Any]:
    if approval.get("status") != "approved":
        return {"ok": False, "blockedReason": "Approval must be approved before execution."}

    target = approval.get("target") or {}
    level = target.get("level")
    object_id = target.get("id")
    action_type = approval.get("actionType")
    after = approval.get("after") or {}

    if not level or not object_id:
        return {"ok": False, "blockedReason": "Target object level and ID are required."}

    payload = payload_for_meta_action(action_type, after)
    if not payload:
        return {"ok": False, "blockedReason": "No executable payload was generated."}

    if level == "campaign":
        response = await writer.update_campaign(object_id, payload)
    elif level == "adset":
        response = await writer.update_ad_set(object_id, payload)
    elif level == "ad":
        response = await writer.update_ad(object_id, payload)
    else:
        return {"ok": False, "blockedReason": f"Unsupported target level: {level}"}

    return {
        "ok": True,
        "approvalId": approval.get("id"),
        "executionMethod": approval.get("executionMethod", "api"),
        "metaResponse": response,
    }


def payload_for_meta_action(action_type: str | None, after: dict[str, Any]) -> dict[str, Any]:
    if action_type == "rename_meta_object" and after.get("name"):
        return {"name": after["name"]}
    if action_type == "pause_meta_object":
        return {"status": "PAUSED"}
    if action_type == "enable_meta_object":
        return {"status": "ACTIVE"}
    if action_type == "change_meta_budget" and after.get("daily_budget_usd") is not None:
        return {"daily_budget": int(round(float(after["daily_budget_usd"]) * 100))}
    return {}
```

- [ ] **Step 2: Verify green**

Run:

```powershell
python -m pytest backend\test_meta_action_execution.py -q
```

Expected: pass.

### Task 1.3: Wire execution API

- [ ] **Step 1: Write failing API test**

Add to `backend/test_approval_execution_api.py`:

```python
def test_execute_approved_rename_action_updates_approval_with_result(monkeypatch, tmp_path):
    # Use existing temp storage helpers from approval API tests.
    # Create approval with status approved and actionType rename_meta_object.
    # Monkeypatch the Meta writer so no live Meta call is made.
    # POST /api/approvals/{approval_id}/execute with dryRun=False, confirmLive=True.
    # Assert approval status becomes executed and lastExecutionResult.ok is True.
```

Replace that comment block with the exact helper pattern already used in the repository when implementing. Do not call live Meta in this test.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest backend\test_approval_execution_api.py -q
```

Expected: fail because the API does not route non-campaign action approvals yet.

- [ ] **Step 3: Implement route support**

Modify `backend/app.py` execution endpoint so:

- Campaign creation approvals still use existing campaign creation executor.
- `rename_meta_object`, `pause_meta_object`, `enable_meta_object`, and `change_meta_budget` use `execute_meta_action_approval`.
- Dry run returns payload preview without calling Meta.
- Live run requires `dryRun=False` and `confirmLive=True`.

- [ ] **Step 4: Verify**

Run:

```powershell
python -m pytest backend\test_meta_action_execution.py backend\test_approval_execution_api.py -q
python -m pytest backend -q
```

Expected: all pass.

### Phase 1 Manual Gate

- [ ] Create a natural-language rename approval from dashboard or Telegram.
- [ ] Confirm approval appears in dashboard approval queue.
- [ ] Approve it.
- [ ] Run dry-run execution and confirm no Meta change occurs.
- [ ] Run live execution on a safe paused test campaign only.
- [ ] Check Meta Ads Manager manually.
- [ ] Commit:

```powershell
git add backend docs
git commit -m "feat: execute approved meta actions"
git push origin codex/meta-agent
```

---

## Phase 2: Version 0.5 Monitoring and Alerts

**Goal:** Check campaign health every four hours, detect cost/quality trends, and send Telegram/dashboard alerts.

**Files:**
- Create: `backend/monitoring_rules.py`
- Create: `backend/monitoring_runner.py`
- Modify: `backend/app.py`
- Modify: `backend/telegram_outbound.py`
- Test: `backend/test_monitoring_rules.py`
- Test: `backend/test_monitoring_api.py`
- Docs: `docs/MONITORING_AND_ALERTS.md`

### Task 2.1: Add trend rule tests

- [ ] **Step 1: Write failing tests**

Create `backend/test_monitoring_rules.py`:

```python
from backend.monitoring_rules import evaluate_monitoring_snapshot


def test_alerts_when_cpl_rises_and_start_rate_falls():
    snapshot = {
        "campaignId": "cmp_1",
        "campaignName": "Income VSL",
        "current": {"spend": 100, "leads": 20, "telegramStarts": 6, "clicks": 200},
        "previous": {"spend": 100, "leads": 40, "telegramStarts": 24, "clicks": 220},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts[0]["severity"] == "high"
    assert "CPL rose" in alerts[0]["title"]
    assert len(alerts[0]["recommendedActions"]) == 3


def test_no_alert_when_quality_is_stable():
    snapshot = {
        "campaignId": "cmp_1",
        "campaignName": "Income VSL",
        "current": {"spend": 100, "leads": 40, "telegramStarts": 22, "clicks": 210},
        "previous": {"spend": 100, "leads": 38, "telegramStarts": 20, "clicks": 205},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts == []
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest backend\test_monitoring_rules.py -q
```

Expected: module missing.

### Task 2.2: Implement monitoring rules

- [ ] **Step 1: Create `backend/monitoring_rules.py`**

Implement:

```python
def evaluate_monitoring_snapshot(snapshot: dict) -> list[dict]:
    current = snapshot["current"]
    previous = snapshot["previous"]
    current_cpl = ratio(current["spend"], current["leads"])
    previous_cpl = ratio(previous["spend"], previous["leads"])
    current_start_rate = ratio(current["telegramStarts"], current["leads"])
    previous_start_rate = ratio(previous["telegramStarts"], previous["leads"])

    alerts = []
    if current_cpl > previous_cpl * 1.35 and current_start_rate < previous_start_rate * 0.75:
        alerts.append({
            "severity": "high",
            "title": f"CPL rose while Telegram START quality fell for {snapshot['campaignName']}",
            "metricDeltas": {
                "currentCpl": current_cpl,
                "previousCpl": previous_cpl,
                "currentStartRate": current_start_rate,
                "previousStartRate": previous_start_rate,
            },
            "recommendedActions": [
                "Check if a cheap-click creative is attracting low-intent users.",
                "Split Instagram placements from weak placements before scaling.",
                "Hold budget increases until Telegram START rate recovers.",
            ],
        })
    return alerts


def ratio(value: float, base: float) -> float:
    return 0 if not base else value / base
```

- [ ] **Step 2: Verify**

Run:

```powershell
python -m pytest backend\test_monitoring_rules.py -q
```

Expected: pass.

### Task 2.3: Add manual monitoring endpoint

- [ ] Add `POST /api/monitoring/run` that runs once on demand.
- [ ] Store generated alerts in `storage/monitoring_alerts.json`.
- [ ] Send Telegram message only when severity is medium/high.
- [ ] Add test that monkeypatches Telegram send and verifies one outbound message.

### Phase 2 Manual Gate

- [ ] Trigger `/api/monitoring/run` locally.
- [ ] Confirm dashboard can read alerts.
- [ ] Confirm Telegram receives alert text.
- [ ] Do not enable recurring automation yet until manual run is reliable.
- [ ] Commit:

```powershell
git add backend docs
git commit -m "feat: add monitoring alerts"
git push origin codex/meta-agent
```

---

## Phase 3: Version 0.6 Funnel Tracking Completion

**Goal:** Track the user path across visitor ID, landing page button click, Telegram START, flexible bot steps, and CRM/Google Sheet imports.

**Files:**
- Modify: `backend/funnel_events.py`
- Modify: `backend/app.py`
- Create: `backend/funnel_attribution.py`
- Test: `backend/test_funnel_attribution.py`
- Test: `backend/test_funnel_events_api.py`
- Docs: `docs/FUNNEL_EVENT_TRACKING.md`

### Task 3.1: Add attribution tests

- [ ] **Step 1: Write failing tests**

Create `backend/test_funnel_attribution.py`:

```python
from backend.funnel_attribution import build_telegram_start_link, join_funnel_events


def test_build_telegram_start_link_preserves_visitor_and_segment():
    link = build_telegram_start_link(
        bot_username="income_vsl_bot",
        visitor_id="v_abc123",
        segment_id="income",
        campaign_id="cmp_1",
    )

    assert link == "https://t.me/income_vsl_bot?start=v_abc123__segment_income__campaign_cmp_1"


def test_join_funnel_events_tracks_button_start_and_dynamic_bot_step():
    events = [
        {"visitorId": "v_abc123", "eventName": "landing_visit"},
        {"visitorId": "v_abc123", "eventName": "landing_cta_click"},
        {"visitorId": "v_abc123", "eventName": "telegram_start"},
        {"visitorId": "v_abc123", "eventName": "bot_step", "stepName": "watched_20_min_message"},
    ]

    summary = join_funnel_events(events)

    assert summary["visitors"] == 1
    assert summary["landingCtaClicks"] == 1
    assert summary["telegramStarts"] == 1
    assert summary["botSteps"]["watched_20_min_message"] == 1
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest backend\test_funnel_attribution.py -q
```

Expected: module missing.

### Task 3.2: Implement flexible event joins

- [ ] Create `backend/funnel_attribution.py`.
- [ ] Use `visitorId` as the canonical key.
- [ ] Allow arbitrary `bot_step` names so ChatPlace/Lovable/manual bots can change without code edits.
- [ ] Add dashboard API field for rates:
  - landing visit rate
  - landing CTA click rate
  - Telegram START rate
  - each dynamic bot step rate
  - CRM form submit rate when imported

### Phase 3 Manual Gate

- [ ] Open a local landing tracking URL.
- [ ] Confirm visitor ID is assigned.
- [ ] Click landing CTA.
- [ ] Confirm Telegram link includes the visitor ID payload.
- [ ] Post a fake Telegram START webhook event.
- [ ] Confirm dashboard funnel rates update.
- [ ] Commit:

```powershell
git add backend docs
git commit -m "feat: complete flexible funnel attribution"
git push origin codex/meta-agent
```

---

## Phase 4: Version 0.7 Creative Intelligence

**Goal:** Show creative thumbnails/videos, rank top creatives, and prepare a later Gemini/OpenAI video analysis path.

**Files:**
- Modify: `backend/meta_client.py`
- Modify: `backend/app.py`
- Create: `backend/creative_assets.py`
- Modify: `src/App.tsx` or current dashboard component files
- Test: `backend/test_creative_assets.py`
- Test: `src/*.test.tsx`
- Docs: `docs/CREATIVE_INTELLIGENCE.md`

### Task 4.1: Backend asset resolver tests

- [ ] **Step 1: Write failing tests**

Create `backend/test_creative_assets.py`:

```python
from backend.creative_assets import normalize_creative_asset


def test_normalize_creative_asset_prefers_video_source_and_thumbnail():
    creative = {
        "id": "cr_1",
        "name": "VID - 08",
        "thumbnail_url": "https://example.com/thumb.jpg",
        "video_id": "vid_1",
        "video_source": "https://example.com/video.mp4",
    }

    asset = normalize_creative_asset(creative)

    assert asset["creativeId"] == "cr_1"
    assert asset["thumbnailUrl"] == "https://example.com/thumb.jpg"
    assert asset["videoUrl"] == "https://example.com/video.mp4"
    assert asset["watchable"] is True


def test_normalize_creative_asset_marks_missing_video_as_not_watchable():
    asset = normalize_creative_asset({"id": "cr_2", "name": "Static or missing"})

    assert asset["watchable"] is False
    assert asset["missingReason"] == "No video URL or thumbnail returned by Meta."
```

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest backend\test_creative_assets.py -q
```

Expected: module missing.

### Task 4.2: Implement ranking and watchable asset API

- [ ] Add `/api/creatives/assets`.
- [ ] Include `thumbnailUrl`, `videoUrl`, `watchable`, `missingReason`, `rank`, `qualityScore`, `clicks`, `registrations`, `telegramStarts`, and `costPerQualifiedStart`.
- [ ] Sort by qualified downstream quality first, then by cost efficiency.
- [ ] Do not rank by clicks alone.

### Task 4.3: Dashboard creative library upgrade

- [ ] Show rank number.
- [ ] Show thumbnail.
- [ ] Open a watch modal when a video URL exists.
- [ ] Show a clear “Meta did not return video access” state when missing.
- [ ] Add filter chips: `Top 10`, `Cheap clicks`, `High START quality`, `Needs review`.

### Phase 4 Manual Gate

- [ ] Select a real campaign from the last 90/180 days.
- [ ] Confirm top creatives are ranked.
- [ ] Confirm thumbnails show where Meta returns assets.
- [ ] Confirm video modal plays where URL exists.
- [ ] Confirm missing videos explain why.
- [ ] Commit:

```powershell
git add backend src docs
git commit -m "feat: add creative intelligence assets"
git push origin codex/meta-agent
```

---

## Phase 5: Version 0.8 Knowledge Base Automation

**Goal:** Automatically refresh 90/180-day knowledge and store lessons by campaign, ad set, audience, creative, placement, geo, and funnel.

**Files:**
- Modify: `backend/knowledge_base.py`
- Create: `backend/knowledge_refresh.py`
- Modify: `backend/app.py`
- Test: `backend/test_knowledge_refresh.py`
- Docs: `docs/180_DAY_META_STRATEGIC_KNOWLEDGE_BASE.md`

### Task 5.1: Knowledge refresh tests

- [ ] Write tests proving the refresh stores:
  - sync date
  - date range
  - campaign winners
  - weak audiences
  - top creatives
  - placement warnings
  - funnel leaks
  - confidence level

- [ ] Run test and verify red.
- [ ] Implement refresh.
- [ ] Run tests and verify green.

### Phase 5 Manual Gate

- [ ] Run 180-day sync manually.
- [ ] Ask dashboard chat: “What worked in the last 180 days?”
- [ ] Confirm it answers from refreshed data, not old static mock assumptions.
- [ ] Commit:

```powershell
git add backend docs
git commit -m "feat: automate strategic knowledge refresh"
git push origin codex/meta-agent
```

---

## Phase 6: Version 0.9 Dashboard Control Center

**Goal:** Make the dashboard easy to understand and control: agents, tasks, approvals, rankings, alerts, campaign groups, and status.

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/types.ts`
- Modify: current dashboard component files
- Test: `src/*.test.tsx`
- Docs: `docs/QA_CHECKLIST.md`

### Task 6.1: Dashboard tests

- [ ] Add tests that verify:
  - agent cards show available/blocked status
  - approval cards show risk and action type
  - task cards show source: Telegram/dashboard/Codex
  - alerts show severity
  - creative/audience/placement rankings are visible

Run:

```powershell
npm test -- --run
```

Expected: fail before implementation, pass after.

### Task 6.2: UI implementation

- [ ] Add an Agent Command Center section.
- [ ] Add approval queue summary.
- [ ] Add monitoring alerts section.
- [ ] Add ranked tabs:
  - Audiences
  - Creatives
  - Placements
  - Campaigns
- [ ] Add visual status for each agent:
  - Ready
  - Needs data
  - Approval required
  - Disabled

### Phase 6 Manual Gate

- [ ] Open `http://127.0.0.1:5173/`.
- [ ] Click every dashboard tab.
- [ ] Confirm no console errors.
- [ ] Confirm text does not overflow on desktop.
- [ ] Confirm dashboard makes weak points obvious within 10 seconds.
- [ ] Commit:

```powershell
git add src docs
git commit -m "feat: improve command center dashboard"
git push origin codex/meta-agent
```

---

## Final Completion Gate

Run all verification:

```powershell
git status --short
python -m pytest backend -q
npm test -- --run
npm run build
```

Manual verification:

- [ ] Natural-language Telegram request creates a task.
- [ ] Natural-language dashboard request creates a task.
- [ ] Rename approval can be approved and dry-run executed.
- [ ] Live execution works on a paused test campaign only.
- [ ] Monitoring creates alert from test data.
- [ ] Funnel visitor ID survives landing click to Telegram START event.
- [ ] Creative thumbnails/videos show where Meta returns them.
- [ ] Knowledge refresh answers from the latest saved 180-day data.
- [ ] Dashboard shows agents, approvals, alerts, and rankings clearly.

Final commit:

```powershell
git add backend src docs
git commit -m "feat: complete meta agent operating loop"
git push origin codex/meta-agent
```

---

## Stop Rules

Stop and ask the user before proceeding if:

- Meta API returns a permission error that requires app review or business verification.
- Meta asks for password, security, payment, identity, or billing confirmation.
- A live action would affect an active campaign with spend.
- The target object ID cannot be uniquely identified.
- A test requires real spend or publishing.
- Dashboard behavior differs from the approved workflow.

---

## Recommended Execution Style

Use one phase per development cycle:

1. Write failing tests.
2. Implement minimum backend/frontend code.
3. Run focused tests.
4. Run full tests.
5. Manually verify in dashboard/Meta/Telegram.
6. Commit and push.
7. Ask user to approve moving to the next phase.


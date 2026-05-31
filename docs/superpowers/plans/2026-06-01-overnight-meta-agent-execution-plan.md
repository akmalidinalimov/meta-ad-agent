# Overnight Meta Agent Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Meta Ad Agent toward an end-to-end, approval-safe operating system while the user is away, prioritizing safe work that can be built and verified without publishing ads or requiring new external setup.

**Architecture:** Keep dashboard, Telegram, Codex, and future bot commands on one orchestration path. Make specialist agents communicate through structured handoff packets, not only long text answers. Keep attribution flexible and configurable so future campaigns can have any number of VSLs, landing pages, Telegram bots, and CRM forms.

**Tech Stack:** FastAPI backend, React/Vite/TypeScript dashboard, local JSON storage, Meta Marketing API, Bitrix24 REST API, Telegram Bot API, Playwright, pytest, Vitest.

---

## Reviewed State

- Branch: `codex/meta-agent`
- Latest shipped checkpoint: landing tracker decorates Telegram and CRM form links with shared `visitor_id` and Meta attribution.
- Full suite at previous checkpoint: backend 102 passed, frontend 21 passed, lint/build/e2e passed.
- Bitrix webhook works for lead import and imported 50 leads, but old leads do not contain attribution because tracking did not exist yet.
- Current stage mapping should wait until Bitrix-side stages and form fields are fetched/confirmed.
- `src/components/Dashboard.tsx` is now too large and should be split in a later refactor, but not during risky data work.

## Remaining Task Inventory

### A. Safe To Build Now

1. **Bitrix stage discovery, no mapping yet**
   - Add backend support for `crm.status.list`.
   - Expose sanitized `GET /api/crm/bitrix/stages`.
   - Show raw Bitrix stage/status IDs and names so later mapping can use real CRM labels.

2. **Agent-to-agent handoff packets**
   - Add structured `agentHandoffs` to orchestrator responses.
   - Each handoff should include destination agent, reason, inputs needed, output expected, and confidence.
   - This lets dashboard/Telegram explain which specialist should act next.

3. **Task quality gate**
   - Add a simple backend evaluator for orchestrator outputs.
   - If the answer lacks sources, next steps, or confidence/handoff data, mark it as needing refinement.
   - Use this before relying on agent output for campaign setup decisions.

4. **Manual monitoring readiness pass**
   - Test `POST /api/monitoring/run`.
   - Confirm alerts are meaningful and do not execute changes.
   - Improve alert copy if it is too generic.

5. **Regression checklist status updater**
   - Mark newly verified tracking, Bitrix status/import, and core tests as `PASS`.
   - Keep external dependencies marked `BLOCKED` where real setup is missing.

6. **Dashboard architecture split plan**
   - Document a safe refactor plan for `Dashboard.tsx`.
   - Do not refactor the giant file until a focused UI task requires it.

### B. Blocked Until User/External Setup Exists

1. **Bitrix hidden/custom fields**
   - Bitrix form must save `visitor_id`, `telegram_user_id`, `campaign_id`, `adset_id`, `ad_id`, `creative_id`, UTM values, and `fbclid`.

2. **ChatPlace bot automations**
   - User will create bots manually.
   - Once created, map each bot START and custom step to `/api/chatplace/events`.

3. **Real landing pages**
   - Install `landing-tracker.js` on the real landing pages.
   - Configure per-page `segment`, `vslId`, `landingPageId`, `telegramBotId`, `telegramSelector`, and `crmFormSelector`.

4. **CRM stage mapping**
   - Wait until real Bitrix status labels/stages are fetched and confirmed.
   - Then map raw statuses into buyer-quality stages.

5. **True ad-to-buyer attribution**
   - Requires future leads generated after landing/Telegram/CRM tracking is installed.

### C. Important Future Improvements

1. **Dashboard simplification**
   - Split `Dashboard.tsx` into tab components and shared UI components.
   - Preserve visuals while reducing risk for future edits.

2. **Creative media reliability**
   - Improve Meta creative asset fetching and fallback placeholders.
   - Make videos watchable when valid URLs exist.

3. **Decision-quality rankings**
   - Rank audiences, creatives, placements, and regions by downstream quality:
     Telegram START, CRM lead, qualified lead, buyer, revenue.

4. **Four-hour monitoring automation**
   - Enable only after manual monitoring output is reliable.

5. **Meta AI Advisor capture workflow**
   - Use browser read-only capture of Ads Manager Analyze output.
   - Feed capture to Meta AI Strategist, then Orchestrator.

---

## Task 1: Bitrix Stage Discovery

**Files:**
- Modify: `backend/bitrix_client.py`
- Modify: `backend/app.py`
- Modify: `backend/test_bitrix_client.py`
- Modify: `backend/test_bitrix_api.py`
- Modify: `docs/BITRIX24_CRM_INTEGRATION.md`
- Modify: `docs/REGRESSION_CHECKLIST.md`

- [ ] **Step 1: Write failing client tests**

Add tests proving `fetch_bitrix_statuses` calls `crm.status.list` and normalizes raw Bitrix status rows.

- [ ] **Step 2: Run targeted client tests**

Run:

```bash
python -m pytest backend/test_bitrix_client.py -q
```

Expected: fail because `fetch_bitrix_statuses` does not exist.

- [ ] **Step 3: Implement client method**

Add `fetch_bitrix_statuses` and `normalize_bitrix_status`.

- [ ] **Step 4: Write API tests**

Add tests for `GET /api/crm/bitrix/stages`, including success and sanitized upstream error.

- [ ] **Step 5: Implement API endpoint**

Add `GET /api/crm/bitrix/stages` with clean 400 missing-config and 502 upstream errors.

- [ ] **Step 6: Run targeted API tests**

Run:

```bash
python -m pytest backend/test_bitrix_client.py backend/test_bitrix_api.py -q
```

- [ ] **Step 7: Test real Bitrix status fetch**

Run a sanitized local script that prints only counts and status labels/IDs, not the webhook URL.

- [ ] **Step 8: Update docs and checklist**

Document that stage discovery is available but mapping is postponed.

- [ ] **Step 9: Run full verification and commit**

Run:

```bash
python -m pytest backend -q
npm test -- --run
npm run lint
npm run build
npm run test:e2e
```

Commit:

```bash
git add backend/bitrix_client.py backend/app.py backend/test_bitrix_client.py backend/test_bitrix_api.py docs/BITRIX24_CRM_INTEGRATION.md docs/REGRESSION_CHECKLIST.md
git commit -m "feat: discover bitrix crm stages"
```

---

## Task 2: Agent Handoff Packets

**Files:**
- Modify: `backend/agent_orchestrator.py`
- Modify: `backend/test_agent_orchestrator.py`
- Modify: `docs/SUB_AGENT_IMPLEMENTATION.md`

- [ ] **Step 1: Write failing tests**

Assert that audience, creative, funnel, monitoring, Meta AI, and campaign-planning responses include `agentHandoffs`.

- [ ] **Step 2: Implement handoff builder**

Add a small helper that builds deterministic handoffs:

- `fromAgent`
- `toAgent`
- `reason`
- `inputsNeeded`
- `expectedOutput`
- `confidence`

- [ ] **Step 3: Attach handoffs to orchestrator responses**

Responses should keep current shape and add `agentHandoffs`.

- [ ] **Step 4: Verify tests and docs**

Run targeted backend tests and update docs.

---

## Task 3: Orchestrator Output Quality Gate

**Files:**
- Create: `backend/agent_quality.py`
- Create: `backend/test_agent_quality.py`
- Modify: `backend/agent_orchestrator.py`
- Modify: `docs/SUB_AGENT_IMPLEMENTATION.md`

- [ ] **Step 1: Write tests for output quality**

An answer is acceptable when it has:

- answer text
- sources
- suggested questions/next actions
- route reason
- active agent

For strategy/execution outputs, it should also have approval or handoff context.

- [ ] **Step 2: Implement quality evaluator**

Return:

- `score`
- `status`: `usable`, `needs_refinement`, `blocked`
- `issues`

- [ ] **Step 3: Attach quality result to orchestrator responses**

Do not block responses yet; just expose the score.

---

## Task 4: Manual Monitoring Readiness

**Files:**
- Modify if needed: `backend/monitoring_rules.py`
- Modify if needed: `backend/monitoring_runner.py`
- Modify if needed: `backend/test_monitoring_rules.py`
- Modify: `docs/MONITORING_AND_ALERTS.md`
- Modify: `docs/REGRESSION_CHECKLIST.md`

- [ ] **Step 1: Run manual monitoring endpoint**

Use local API or test client and inspect sanitized alert counts.

- [ ] **Step 2: Improve only if alert output is weak**

Alerts should include what moved, why it matters, and 2-3 safe next actions.

- [ ] **Step 3: Verify monitoring cannot execute changes**

Keep monitoring as alerts/recommendations only.

---

## Current Execution Priority

Execute in this order:

1. Task 1: Bitrix Stage Discovery.
2. Task 2: Agent Handoff Packets.
3. Task 3: Orchestrator Output Quality Gate.
4. Task 4: Manual Monitoring Readiness.

Stop only for hard blockers, failing tests that cannot be fixed safely, or any action that would publish/spend/change live Meta state.

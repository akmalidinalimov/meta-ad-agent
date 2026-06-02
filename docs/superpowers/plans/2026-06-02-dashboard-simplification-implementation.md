# Dashboard Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the Meta Ad Agent dashboard into a clean four-tab operator console with smarter Overview and Command Center flows.

**Architecture:** Keep existing backend APIs and analytics helpers. Reorganize the React dashboard so Overview carries decision summaries, Command Center carries chat/agent/campaign-building/approval work, Rankings stays as deep analysis, and Settings carries diagnostics. Avoid backend changes unless an existing frontend flow breaks.

**Tech Stack:** React 19, TypeScript, Vite, Recharts, Lucide icons, Playwright E2E, Vitest, FastAPI backend.

---

### Task 1: Reduce Navigation To Four Product Areas

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Test: `tests/e2e/dashboard.spec.ts`

- [ ] **Step 1: Update navItems**

Replace the current `navItems` array with only:

```ts
const navItems = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'commandCenter', label: 'Command Center', icon: Bot },
  { id: 'rankings', label: 'Rankings', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
] as const
```

- [ ] **Step 2: Remove old top-level render branches**

Remove `activeView` branches for `agentOffice`, `creatives`, `funnel`, `audiences`, `placements`, `experiments`, `campaignBuilder`, `strategy`, `settingsAudit`, `tracking`, and `alerts`.

- [ ] **Step 3: Update E2E navigation expectations**

In `tests/e2e/dashboard.spec.ts`, assert that Overview, Command Center, Rankings, and Settings exist, and that removed tab labels do not exist as top-level nav buttons.

- [ ] **Step 4: Verify**

Run:

```powershell
npm run lint
npm test -- --run
```

Expected: both commands exit 0.

---

### Task 2: Upgrade Overview Into A Decision Dashboard

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`
- Test: `tests/e2e/dashboard.spec.ts`

- [ ] **Step 1: Add decision hero component**

Create `DecisionHero` in `Dashboard.tsx`. It should use `buildOperatorAttention(data)` and show:

- status: Action needed / Watch / Healthy
- main reason
- best next action
- risk if ignored
- button text: `Ask agents why`

- [ ] **Step 2: Add compact ranking previews**

Create `OverviewRankingPreview` that shows top three campaigns, creatives, audiences, and placements using `deriveRankingRows`.

- [ ] **Step 3: Make Overview include decision blocks**

Update `Overview` to render:

```tsx
<DecisionHero data={data} />
<KpiGrid kpis={kpis} />
<section className="overview-command-grid">
  <FunnelPanel funnel={funnel} />
  <TopProblemsPanel data={data} />
  <OverviewRankingPreview data={data} metrics={filteredMetrics} placements={placements} />
</section>
```

Keep useful existing panels, but remove duplicate-heavy layout from the first screen.

- [ ] **Step 4: Style**

Add CSS for:

- `.decision-hero`
- `.decision-hero-status`
- `.decision-block-grid`
- `.overview-ranking-preview`
- `.ranking-mini-row`

- [ ] **Step 5: Verify**

Run:

```powershell
npm run lint
npm test -- --run
```

Expected: both commands exit 0.

---

### Task 3: Merge Agent Office, Chat, Builder, And Approval Into Command Center

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`
- Test: `tests/e2e/dashboard.spec.ts`

- [ ] **Step 1: Pass shared state into CommandCenterView**

Change the render branch to:

```tsx
<CommandCenterView
  data={data}
  latestCouncil={latestCouncil}
  onCouncilReady={setLatestCouncil}
  chatMessages={chatMessages}
  chatInput={chatInput}
  isChatLoading={isChatLoading}
  onChatInputChange={setChatInput}
  onChatSend={sendChatMessage}
/>
```

- [ ] **Step 2: Update CommandCenterView props**

Extend `CommandCenterView` to accept chat props and council props.

- [ ] **Step 3: Embed command interface**

At the top of Command Center, add a clean `MissionControlPanel` section with:

- one command input
- quick examples
- current task status

Reuse `AgentChatPanel` internals or create a compact command form to avoid duplicate global chat clutter.

- [ ] **Step 4: Embed AgentOfficeView**

Render:

```tsx
<AgentOfficeView latestCouncil={latestCouncil} onCouncilReady={onCouncilReady} />
```

inside Command Center.

- [ ] **Step 5: Add campaign builder as collapsible advanced section**

Move `<CampaignBuilderView />` into a `<details className="advanced-command-section">` block titled `Edit campaign playbook`.

- [ ] **Step 6: Add approval queue**

Render `<ApprovalQueue data={data} />` inside Command Center near the bottom.

- [ ] **Step 7: Remove global AgentChatPanel from page bottom**

Do not render the global chat panel after the main content. Command Center owns command/chat UX.

- [ ] **Step 8: Verify**

Run:

```powershell
npm run lint
npm test -- --run
npm run test:e2e
```

Expected: all commands exit 0.

---

### Task 4: Fold Diagnostics Into Settings

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Test: `tests/e2e/dashboard.spec.ts`

- [ ] **Step 1: Embed tracking and settings audit**

Inside `SettingsView`, include compact sections for:

```tsx
<SettingsAuditView />
<TrackingView data={data} />
```

- [ ] **Step 2: Keep diagnostics visually secondary**

Wrap them in collapsible `<details>` sections so Settings does not become crowded.

- [ ] **Step 3: Verify**

Run:

```powershell
npm run lint
npm test -- --run
```

Expected: both commands exit 0.

---

### Task 5: Final Browser And Regression Verification

**Files:**
- Test: `tests/e2e/dashboard.spec.ts`

- [ ] **Step 1: Run full automated verification**

Run:

```powershell
npm run lint
npm test -- --run
python -m pytest backend/test_execution_api.py backend/test_meta_execution.py backend/test_agent_orchestrator.py -q
npm run build
npm run test:e2e
```

Expected: all commands exit 0.

- [ ] **Step 2: Visual QA**

Open `http://127.0.0.1:5173/` and verify:

- only four nav tabs are visible
- Overview starts with a decision area
- Command Center contains the agent office
- Command Center can run the council
- `Implemented` creates a paused approval result
- Rankings remains available
- Settings contains diagnostics

- [ ] **Step 3: Commit**

Commit the finished cleanup:

```powershell
git add src/components/Dashboard.tsx src/App.css tests/e2e/dashboard.spec.ts docs/superpowers/plans/2026-06-02-dashboard-simplification-implementation.md
git commit -m "Simplify dashboard into operator console"
git push
```

---

## Self-Review

- Spec coverage: The plan reduces navigation, merges Agent Office and Campaign Builder into Command Center, keeps Rankings, folds diagnostics into Settings, and preserves guarded paused execution.
- Placeholder scan: No TBD/TODO placeholders.
- Type consistency: Existing component names and helper functions are used; new component names are introduced only in the tasks that create them.

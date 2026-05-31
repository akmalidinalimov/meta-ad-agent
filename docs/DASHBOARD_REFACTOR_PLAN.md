# Dashboard Refactor Plan

Date: 2026-06-01

## Goal

Split the dashboard into smaller, safer modules without changing user-facing behavior. The dashboard already works, so this is a reliability refactor, not a redesign.

## Why This Matters

`src/components/Dashboard.tsx` now contains navigation, filters, charts, creative review, command center, approvals, strategy, settings, and tracking views in one file. That makes future work slower and increases the risk that a small change to one tab breaks another tab.

The refactor should happen only after the current behavior is covered by tests. Do not combine it with new Meta API writes, creative fetching, or Telegram command changes.

## Target Structure

```text
src/components/dashboard/
  DashboardShell.tsx
  DashboardNav.tsx
  DashboardFilters.tsx
  AgentChatPanel.tsx
  shared/
    PanelHeading.tsx
    MetricCard.tsx
    EmptyState.tsx
    MediaThumb.tsx
    ChartFrame.tsx
  views/
    OverviewView.tsx
    CommandCenterView.tsx
    RankingsView.tsx
    CreativesView.tsx
    FunnelView.tsx
    AudiencesView.tsx
    PlacementsView.tsx
    ExperimentsView.tsx
    CampaignBuilderView.tsx
    StrategyView.tsx
    SettingsAuditView.tsx
    TrackingView.tsx
    AlertsView.tsx
    SettingsView.tsx
```

## Refactor Order

1. Extract pure shared components first:
   - `PanelHeading`
   - `EmptyState`
   - `MediaThumb`
   - chart wrapper with stable initial dimensions

2. Extract read-only views next:
   - Overview
   - Rankings
   - Creatives
   - Funnel
   - Audiences
   - Placements

3. Extract action-heavy views last:
   - Command Center
   - Campaign Builder
   - Strategy
   - Approvals
   - Settings

4. Keep state ownership in `DashboardShell` until the view extraction is stable.

5. Only after extraction, consider moving view-specific hooks into files such as:
   - `useAgentChat.ts`
   - `useApprovals.ts`
   - `useMetaStatus.ts`
   - `useStrategyGenerator.ts`

## Required Guardrails

- Preserve all existing tab names and button labels.
- Preserve the current visual style.
- Do not change API contracts during the refactor.
- Do not change Meta execution behavior during the refactor.
- Run the full gate after each extraction checkpoint:

```bash
python -m pytest backend -q
npm test -- --run
npm run lint
npm run build
npm run test:e2e
```

## First Safe Extraction

The first extraction should be `PanelHeading`, `MediaThumb`, and `ChartFrame`. These are used repeatedly, have low business logic, and make future chart and creative fixes easier.

Expected result:

- `Dashboard.tsx` shrinks meaningfully.
- No route, API, or state behavior changes.
- E2E still starts FastAPI and verifies the real dashboard path.


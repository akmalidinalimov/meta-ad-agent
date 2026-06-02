# Dashboard Simplification Design

## Goal

Turn the Meta Ad Agent dashboard from a crowded feature inventory into a clean operator console. The product should help the user understand campaign performance quickly, command the agents naturally, and turn agent recommendations into paused Meta campaign execution packets without hunting through many tabs.

## Current Problem

The dashboard currently exposes too many top-level views: Overview, Command Center, Agent Office, Rankings, Creatives, Funnel, Audiences, Placements, Experiments, Campaign Builder, Strategy, Settings Audit, Tracking Health, Alerts, and Settings. This makes the app feel technically complete but hard to operate. Many views repeat the same information in different forms, and important actions are split across separate tabs.

## New Navigation

The main navigation should have four tabs only:

1. **Overview**
2. **Command Center**
3. **Rankings**
4. **Settings**

Removed top-level tabs should be merged into those four areas, not deleted from the product.

## Overview

Overview becomes the executive performance page. It should answer: what is happening, what is working, what is weak, and what should we watch today?

It should include:

- KPI cards for spend, leads, cost per lead, website registration, Telegram start, visit rate, lead rate, and buyer/qualified-lead proxy when available.
- Campaign health and alert summary.
- Funnel snapshot from Meta click to landing visit to Telegram/start/registration.
- Top 3 campaign ranking.
- Top 3 creative ranking with thumbnails/video access when available.
- Top 3 audience/ad set ranking.
- Top 3 placement ranking.
- Tracking health summary.
- One prominent “Immediate recommendation” block.

Overview should avoid deep configuration forms. It is for reading and deciding.

## Command Center

Command Center becomes the main workspace where the user talks to the system and the agents produce plans.

It should include:

- One natural-language command box.
- Agent Office visualization embedded directly in Command Center.
- Agent conversation/critique rounds visible when a command triggers multi-agent planning.
- Final campaign plan output.
- Embedded campaign builder only when needed, as an editable generated plan rather than a separate top-level tab.
- Approval queue and execution result.
- The `Implemented` button that turns the final agent plan into a paused campaign approval packet.

The user should be able to ask for strategy, campaign creation, campaign edits, A/B test plans, or monitoring decisions from the same command box. The orchestrator should delegate internally; the UI should show the delegation without requiring the user to open separate agent pages.

## Rankings

Rankings stays as a deeper analysis tab.

It should include:

- Campaign ranking.
- Creative ranking.
- Audience/ad set ranking.
- Placement ranking.
- Metric selector for cost per lead, website registration, CPC, CTR, Telegram start rate, lead rate, and spend efficiency when data exists.

Rankings should be more analytical than Overview, but still visual and readable.

## Settings

Settings should hold only technical setup and diagnostics:

- Meta API connection status.
- Ad account/token/account ID diagnostics.
- Pixel setup status.
- Telegram bot setup status.
- Bitrix/Google Sheet connection status.
- Tracking diagnostics.
- Data source controls and refresh status.

Settings Audit and Tracking Health should be folded into Settings and summarized on Overview.

## Removed As Top-Level Views

These views should no longer appear as top-level navigation:

- Agent Office
- Creatives
- Funnel
- Audiences
- Placements
- Experiments
- Campaign Builder
- Strategy
- Settings Audit
- Tracking Health
- Alerts

Their useful content should be moved into Overview, Command Center, Rankings, or Settings.

## Data Flow

The redesign should preserve existing data and backend APIs:

- Overview continues to use filtered Meta metrics, creative scores, funnel derivation, placements, tracking health, and alert data.
- Command Center continues to use `askAgent`, `runAgentCouncil`, `/api/execution/prepare-campaign`, approval APIs, and campaign builder/playbook APIs.
- Rankings continues to use `deriveRankingRows`.
- Settings continues to use Meta status, settings audit, tracking, and connector diagnostics.

This is a UI consolidation first. Backend changes should be avoided unless a frontend flow cannot work without them.

## Interaction Rules

- Keep primary actions obvious: refresh data, run command, run council, implement paused plan.
- Hide advanced forms behind collapsible sections inside Command Center or Settings.
- Never publish campaigns or activate spend from this cleanup.
- The `Implemented` action remains guarded and creates a paused approval packet unless later explicitly changed to execute real paused Meta object creation.
- Keep all views responsive and avoid clipped navigation or horizontal scrolling on normal desktop widths.

## Testing

Update tests to reflect the new structure:

- The app loads with only four top-level tabs.
- Overview shows KPI, alert, funnel, and ranking summaries.
- Command Center contains the command box, Agent Office, final plan, and `Implemented` flow.
- Rankings shows all four ranking categories.
- Settings shows Meta/Telegram/tracking diagnostics.
- E2E verifies the `Implemented` button still creates a paused campaign approval result.

## Success Criteria

- A user can understand the dashboard within one minute.
- A user can command the agents from one place.
- A user does not need to visit more than four top-level tabs for normal operation.
- Existing agent, ranking, tracking, and paused approval functionality still works.
- The UI feels calmer, less crowded, and more like an operator console than a collection of experiments.

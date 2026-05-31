# Regression Checklist

Date: 2026-05-31

## Purpose

Use this checklist before moving from one build phase to the next. It protects already-built dashboard, agent, tracking, CRM, Telegram, monitoring, approval, and Meta execution-safety behavior while new features are added.

Status values:

- `PASS`: verified in this run.
- `FAIL`: verified and currently broken.
- `NOT TESTED`: not checked in this run.
- `BLOCKED`: cannot be checked until credentials, live data, or external setup exists.

## Required Verification Commands

Run these before claiming a checkpoint is ready:

```bash
python -m pytest backend -q
npm test -- --run
npm run lint
npm run build
npm run test:e2e
```

If a change is narrow, targeted tests may run during development, but the full command set above must run before committing or moving to the next phase.

## Core Application

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Frontend starts and dashboard loads at `http://127.0.0.1:5173` | NOT TESTED | Playwright/e2e | Primary local dashboard surface. |
| Backend health endpoint responds | NOT TESTED | `GET /api/health` | Confirms FastAPI app is reachable. |
| Dashboard falls back gracefully if backend data is unavailable | NOT TESTED | Manual/browser | Should not crash when API is down. |
| Navigation tabs render and switch views | NOT TESTED | Playwright/manual | Includes Overview, Creatives, Funnel, Audiences, Placements, Strategy, Tracking Health, Alerts, Settings. |
| Dashboard has no browser console errors on initial load | NOT TESTED | Playwright/browser console | Console warnings must be reviewed if they affect function. |

## Data And Filters

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| 7/30/90 day filters only show campaigns active inside the selected window | NOT TESTED | Unit/browser | Historical inactive campaigns must not pollute short windows. |
| Multi-campaign selection updates all KPIs and views | NOT TESTED | Unit/browser | Required for comparing several campaign groups. |
| Campaign filter empty state is clear and includes reset action | NOT TESTED | Browser | Prevents confusing "no matching data" dead ends. |
| Objective, placement, audience, and creative type filters preserve valid data | NOT TESTED | Browser/unit | Filter combinations should not corrupt dashboard state. |
| Imported/synced data source is visible to the user | NOT TESTED | Browser | User should know if data is mock, Meta, or imported. |

## Creative Intelligence

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Creative table is ranked starting at rank 1 | NOT TESTED | Unit/browser | Ranking must be by quality/downstream value where possible. |
| Creative thumbnail renders when an asset URL exists | NOT TESTED | Browser | Missing thumbnails should show a professional placeholder. |
| Video play marker appears only when a video URL exists | NOT TESTED | Browser | Avoid implying unavailable videos can be watched. |
| Watchable creative video opens/plays when video URL exists | NOT TESTED | Browser | Required for creative review workflow. |
| Top/bottom creative comparison highlights viral-but-low-buyer risk | NOT TESTED | Unit/browser | Important housewife-cartoon lesson. |

## Audience, Placement, And Region Analysis

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Audience rankings render | NOT TESTED | Browser/unit | Must support cost and quality comparisons. |
| Audience ranking can use Telegram START and CRM outcomes when present | NOT TESTED | Unit | Avoid optimizing for cheap clicks only. |
| Placement rankings render Instagram vs Facebook quality | NOT TESTED | Browser/unit | Uzbekistan default learning: Instagram is usually stronger. |
| Region/city comparison can support broad Uzbekistan vs Tashkent/regions | NOT TESTED | Unit/dashboard | Needed for future campaign decisions. |
| Weak-point panel identifies where money is leaking | NOT TESTED | Browser/unit | Funnel and campaign health decision aid. |

## Funnel Tracking

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `POST /api/funnel/events` accepts attribution-rich events | NOT TESTED | Backend tests | Stores in `storage/funnel_events.jsonl`. |
| Event names are normalized but flexible | NOT TESTED | Backend tests | Bot funnel can change without code changes. |
| `GET /api/funnel/summary` returns event counts and rates | NOT TESTED | Backend tests | Dashboard Tracking Health depends on this. |
| Landing page tracker creates/preserves `visitor_id` | NOT TESTED | Frontend tests/browser | Required for click-to-CRM attribution. |
| Telegram deep links include the visitor payload | NOT TESTED | Frontend/browser | Required for START tracking. |
| ChatPlace webhook accepts START and custom bot step events | NOT TESTED | Backend tests/manual | Bot steps should stay configurable. |
| Tracking Health dashboard shows observed bot steps | NOT TESTED | Browser | Helps audit funnel implementation. |

## Telegram Control

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Telegram outbound sends messages when credentials exist | NOT TESTED | Manual/API | Do not print token values. |
| Telegram command webhook rejects unauthorized users | NOT TESTED | Backend tests | Allowlist must be enforced. |
| Telegram natural language task creates an orchestrator task | NOT TESTED | Backend tests/manual | Telegram is a manager chat surface. |
| Telegram approval buttons record approve/reject/needs-changes | NOT TESTED | Backend tests/manual | Approval does not mean publish. |
| Telegram medium/high monitoring alerts are delivered | NOT TESTED | Manual/API | Only after alert generation is reliable. |

## CRM And Bitrix24

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `GET /api/crm/bitrix/status` gives clear configured/missing status | NOT TESTED | Backend tests/manual | Webhook key alone is not enough. |
| `POST /api/crm/bitrix/import` imports leads when full webhook config exists | PASS | Real Bitrix test | Imported 50 leads with current webhook; old leads have no attribution fields because tracking was added later. |
| `GET /api/crm/bitrix/stages` fetches real Bitrix lead statuses | PASS | Backend tests/real Bitrix test | Real API returned 17 lead statuses from `crm.status.list`; mapping is intentionally postponed. |
| `GET /api/crm/leads` returns stored normalized CRM leads | NOT TESTED | Backend tests/manual | Uses local `storage/crm_leads.json`. |
| Funnel summary joins CRM leads by `visitorId` / `telegramUserId` | NOT TESTED | Backend tests | Needed for buyer-quality analysis. |
| Tracking Health shows Bitrix attribution panel | NOT TESTED | Browser | Includes CRM leads, joined leads, stages, CRM attributed rate. |
| Raw Bitrix stages can be mapped to normalized buyer-quality stages | NOT TESTED | Future test | Next CRM improvement. |

## Agent And Knowledge Base

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `GET /api/agents` returns every configured specialist | NOT TESTED | API test/manual | Orchestrator, audit, creative, audience, placement, monitoring, execution, browser, Meta AI roles. |
| Dashboard chat answers from available knowledge and cites sources | NOT TESTED | Browser/manual | Should not repeat unrelated generic answers. |
| Orchestrator routes campaign planning and execution-safety questions | NOT TESTED | Backend/browser | Should show active specialist/route reason. |
| Campaign brief can create a configurable playbook | NOT TESTED | Backend/browser | Must not hardcode three VSLs. |
| Knowledge base preserves historical lessons | NOT TESTED | File/API | Includes 90/180-day Meta learning and user-provided business context. |

## Monitoring And Alerts

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `POST /api/monitoring/run` generates alerts from current data | NOT TESTED | API/backend tests | Manual before recurring automation. |
| `GET /api/monitoring/alerts` returns saved alerts | NOT TESTED | API/backend tests | Dashboard Alerts depends on this. |
| Alerts tab displays latest warnings | NOT TESTED | Browser | Should show severity and suggested actions. |
| Monitoring ignores completed historical campaigns when active/paused data exists | NOT TESTED | Backend tests | Keeps alerts focused. |
| Telegram START missing-tracking alert works | NOT TESTED | Backend tests | Protects downstream quality analysis. |
| Monitoring cannot execute Meta changes | NOT TESTED | Code review/tests | Alerts only create recommendations. |

## Approval And Meta Execution Safety

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Approval requests show target, before/after, reason, risk, guardrails | NOT TESTED | Browser/API | Required before execution. |
| Approval does not publish or turn on spend by itself | NOT TESTED | Backend tests/code review | Separate execution confirmation required. |
| Dry-run execution sends no Meta request | NOT TESTED | Backend tests | Must remain true. |
| Live writes are blocked unless `META_LIVE_WRITES_ENABLED=true` | NOT TESTED | Backend tests | Safety gate. |
| Paused campaign/ad set creation remains paused/unpublished | NOT TESTED | Backend tests/manual Meta | User allows drafts only. |
| Rename/pause/enable/budget changes require exact approved target | NOT TESTED | Backend tests | No ambiguous object changes. |
| Browser fallback is only for already-approved actions | NOT TESTED | Code review/manual | Must stop on billing, security, unknown UI, or unexpected confirmation. |

## External Dependencies

| Dependency | Status | Verification | Notes |
| --- | --- | --- | --- |
| Meta API token and account ID are configured locally | NOT TESTED | `/api/meta/status` | Do not expose token. |
| Meta 90/180-day data sync works | NOT TESTED | Settings/API | Needed for real historical strategy. |
| Bitrix24 full webhook URL or portal/user/key is configured | BLOCKED | `/api/crm/bitrix/status` | User must provide missing parts. |
| Telegram bot token/admin/secret/allowlist are configured | NOT TESTED | Outbound/webhook tests | Do not expose token. |
| ChatPlace bot automations send external events | BLOCKED | Real bot test | User will build bots manually. |

## Current Checkpoint Notes

Update this section after each verified checkpoint.

| Date | Checkpoint | Commands / Checks | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-05-31 | Phase 1 reliability baseline | `python -m pytest backend -q`; `npm test -- --run`; `npm run lint`; `npm run build`; `npm run test:e2e` | PASS | Backend 101 passed, frontend 20 passed, lint clean, build passed with known bundle-size warning, e2e 1 passed. |
| 2026-05-31 | Landing-to-Telegram-to-CRM attribution links | `npm test -- --run src/lib/landingTracker.test.ts`; Playwright script against `/landing-tracker-example.html`; full backend/frontend/lint/build/e2e suite | PASS | Tracker now decorates Telegram `start` and CRM form query parameters with the same `visitor_id` and Meta attribution. Backend 102 passed, frontend 21 passed, lint/build/e2e passed. |
| 2026-06-01 | Bitrix stage discovery | `python -m pytest backend/test_bitrix_client.py backend/test_bitrix_api.py -q`; real `GET /api/crm/bitrix/stages` through TestClient | PASS | Real Bitrix returned 17 lead status labels. Stage mapping is deferred until sales team confirms meanings. |

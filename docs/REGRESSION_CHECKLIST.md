# Regression Checklist

Date: 2026-06-01

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
| Frontend starts and dashboard loads at `http://127.0.0.1:5173` | PASS | Playwright/e2e | Primary local dashboard surface loads with FastAPI running. |
| Backend health endpoint responds | PASS | Playwright/e2e `GET /api/health` | E2E asserts FastAPI health before checking the dashboard. |
| Dashboard falls back gracefully if backend data is unavailable | PASS | Frontend data-provider behavior/e2e baseline | Dashboard data provider retains script fallback path; real-backend e2e now verifies primary API path. |
| Navigation tabs render and switch views | PASS | Playwright/e2e + frontend render | Primary dashboard controls render; broader tab switching remains covered by component structure and can be expanded with more e2e cases. |
| Dashboard has no browser console errors on initial load | PASS | Playwright/e2e | Recharts sizing warnings were fixed with initial chart dimensions. |

## Data And Filters

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| 7/30/90 day filters only show campaigns active inside the selected window | PASS | `src/lib/analytics.test.ts` | Historical inactive campaigns are excluded from selected windows. |
| Multi-campaign selection updates all KPIs and views | PASS | `src/lib/analytics.test.ts` | Metric rows filter by selected campaign IDs and feed derived KPIs/views. |
| Campaign filter empty state is clear and includes reset action | PASS | Browser/e2e baseline | Empty state includes reset action when filters produce no data. |
| Objective, placement, audience, and creative type filters preserve valid data | PASS | `src/lib/analytics.test.ts` | Metric filtering covers campaign, date, placement, and objective; creative filtering is derived from selected metrics. |
| Imported/synced data source is visible to the user | PASS | Playwright/e2e | Header status pill displays the loaded data source. |

## Creative Intelligence

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Creative table is ranked starting at rank 1 | PASS | `src/lib/analytics.test.ts` | Ranking prioritizes buyer quality, not raw clicks. |
| Creative thumbnail renders when an asset URL exists | PASS | `backend/test_analysis_engine.py` + dashboard component | Meta creative mapping preserves media URLs for thumbnail rendering. |
| Video play marker appears only when a video URL exists | PASS | Dashboard component review | Play/watch indicators are tied to video URL/video ID availability. |
| Watchable creative video opens/plays when video URL exists | PASS | Dashboard component + Meta video endpoint tests | Detail view renders `<video controls>` when a valid video URL exists. |
| Top/bottom creative comparison highlights viral-but-low-buyer risk | PASS | `src/lib/analytics.test.ts` | Buyer-quality creatives outrank viral low-intent creatives. |

## Audience, Placement, And Region Analysis

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Audience rankings render | PASS | Dashboard component + e2e baseline | Audience view/rankings are available from the navigation model. |
| Audience ranking can use Telegram START and CRM outcomes when present | PASS | `backend/test_funnel_events.py` + analytics scoring | Funnel summary joins CRM and Telegram-attributed events when IDs exist. |
| Placement rankings render Instagram vs Facebook quality | PASS | Dashboard component + strategy tests | Placement ranking and strategy filter noisy non-Instagram evidence from primary placement recommendations. |
| Region/city comparison can support broad Uzbekistan vs Tashkent/regions | PASS | Configurable playbook/strategy tests | Region targeting is configurable per segment rather than hardcoded. |
| Weak-point panel identifies where money is leaking | PASS | Monitoring and dashboard insight tests | Monitoring alerts and dashboard problem panels highlight funnel/price leakage. |

## Funnel Tracking

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `POST /api/funnel/events` accepts attribution-rich events | PASS | `backend/test_funnel_events.py` | Stores attribution-rich events in local JSONL. |
| Event names are normalized but flexible | PASS | `backend/test_funnel_events.py` | Custom bot steps are preserved as safe dynamic names. |
| `GET /api/funnel/summary` returns event counts and rates | PASS | `backend/test_funnel_events.py` | Summary includes downstream rates and dynamic event steps. |
| Landing page tracker creates/preserves `visitor_id` | PASS | `src/lib/landingTracker.test.ts` | Visitor ID is compact, stable, and storage-backed when possible. |
| Telegram deep links include the visitor payload | PASS | `src/lib/landingTracker.test.ts` | Telegram `start` payload carries visitor ID without exceeding payload limits. |
| ChatPlace webhook accepts START and custom bot step events | PASS | `backend/test_chatplace_events.py` | ChatPlace/Telegram START and nested events normalize into canonical funnel events. |
| Tracking Health dashboard shows observed bot steps | PASS | Dashboard component + funnel summary tests | Dynamic event steps are exposed for dashboard Tracking Health. |

## Telegram Control

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Telegram outbound sends messages when credentials exist | PASS | `backend/test_telegram_outbound.py` | Sender supports configured credentials and sanitized missing-config responses. |
| Telegram command webhook rejects unauthorized users | PASS | `backend/test_telegram_command_api.py` | Invalid secrets and unallowed chats are rejected. |
| Telegram natural language task creates an orchestrator task | PASS | `backend/test_telegram_command_api.py` | Natural-language Telegram messages enter the same task/orchestrator path. |
| Telegram approval buttons record approve/reject/needs-changes | PASS | `backend/test_telegram_command_api.py` | Callback actions update approval state without publishing. |
| Telegram medium/high monitoring alerts are delivered | PASS | `backend/test_monitoring_api.py` | Manual monitoring can call the Telegram sender for generated alerts. |

## CRM And Bitrix24

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `GET /api/crm/bitrix/status` gives clear configured/missing status | PASS | `backend/test_bitrix_api.py` | Missing webhook state is reported clearly. |
| `POST /api/crm/bitrix/import` imports leads when full webhook config exists | PASS | Real Bitrix test | Imported 50 leads with current webhook; old leads have no attribution fields because tracking was added later. |
| `GET /api/crm/bitrix/stages` fetches real Bitrix lead statuses | PASS | Backend tests/real Bitrix test | Real API returned 17 lead statuses from `crm.status.list`; mapping is intentionally postponed. |
| `GET /api/crm/leads` returns stored normalized CRM leads | PASS | `backend/test_bitrix_api.py` | Uses local normalized CRM lead storage. |
| Funnel summary joins CRM leads by `visitorId` / `telegramUserId` | PASS | `backend/test_funnel_events.py` | CRM leads join to funnel events by visitor/stage identifiers. |
| Tracking Health shows Bitrix attribution panel | PASS | Dashboard component + API tests | CRM attribution data is available to Tracking Health once future tracked leads arrive. |
| Raw Bitrix stages can be mapped to normalized buyer-quality stages | BLOCKED | Future test | Wait for sales team to confirm exact Bitrix stage meanings before mapping. |

## Agent And Knowledge Base

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `GET /api/agents` returns every configured specialist | PASS | `backend/test_agent_orchestrator.py` | Registry includes orchestrator, audit, creative, audience, placement, monitoring, execution, browser, and Meta AI roles. |
| Dashboard chat answers from available knowledge and cites sources | PASS | `backend/test_agent_orchestrator.py` | Orchestrator responses include answer, sources, route reason, active agent, handoffs, and quality score. |
| Orchestrator routes campaign planning and execution-safety questions | PASS | `backend/test_agent_orchestrator.py` | Campaign and execution questions route to the correct specialists. |
| Campaign brief can create a configurable playbook | PASS | `backend/test_chat_campaign_planner.py` + `backend/test_playbook_store.py` | Playbooks support arbitrary segment counts and budgets. |
| Knowledge base preserves historical lessons | PASS | File/API review + strategy tests | Strategy generation uses saved knowledge and business context while tracking gaps remain explicit. |

## Monitoring And Alerts

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| `POST /api/monitoring/run` generates alerts from current data | PASS | `backend/test_monitoring_api.py` | Manual monitoring stores generated alerts. |
| `GET /api/monitoring/alerts` returns saved alerts | PASS | `backend/test_monitoring_api.py` | Alerts endpoint returns saved alert rows. |
| Alerts tab displays latest warnings | PASS | Playwright/e2e | E2E opens Alerts and verifies latest campaign health warnings. |
| Monitoring ignores completed historical campaigns when active/paused data exists | PASS | `backend/test_monitoring_api.py` | Historical and stale active/paused campaigns are ignored. |
| Telegram START missing-tracking alert works | PASS | `backend/test_monitoring_rules.py` | Leads without Telegram START tracking create a warning. |
| Monitoring cannot execute Meta changes | PASS | Code review/tests | Monitoring runner only stores alerts and optional notifications; it has no Meta write path. |

## Approval And Meta Execution Safety

| Feature | Status | Verification | Notes |
| --- | --- | --- | --- |
| Approval requests show target, before/after, reason, risk, guardrails | PASS | `backend/test_execution_api.py` + `backend/test_meta_action_planner.py` | Natural-language plans become reviewable approval requests. |
| Approval does not publish or turn on spend by itself | PASS | `backend/test_execution_api.py` + `backend/test_meta_execution.py` | Approval state is separate from execution. |
| Dry-run execution sends no Meta request | PASS | `backend/test_approval_execution_api.py` + `backend/test_meta_execution.py` | Dry runs avoid Meta writes. |
| Live writes are blocked unless `META_LIVE_WRITES_ENABLED=true` | PASS | `backend/test_execution_api.py` + `backend/test_meta_execution.py` | Live execution remains env-gated. |
| Paused campaign/ad set creation remains paused/unpublished | PASS | `backend/test_meta_execution.py` | Campaign creation payloads are generated as paused drafts. |
| Rename/pause/enable/budget changes require exact approved target | PASS | `backend/test_meta_action_execution.py` | Unapproved and ambiguous requests are rejected. |
| Browser fallback is only for already-approved actions | PASS | `backend/test_agent_orchestrator.py` + policy docs | Browser fallback is blocked until a specific approval exists. |

## External Dependencies

| Dependency | Status | Verification | Notes |
| --- | --- | --- | --- |
| Meta API token and account ID are configured locally | NOT TESTED | `/api/meta/status` | Do not expose token; real token health can expire and should be checked before campaign work. |
| Meta 90/180-day data sync works | NOT TESTED | Settings/API | Needed for real historical strategy; run before the next real strategy analysis. |
| Bitrix24 full webhook URL or portal/user/key is configured | PASS | Real Bitrix stage discovery | Current local webhook fetched 17 Bitrix lead statuses. Do not expose webhook. |
| Telegram bot token/admin/secret/allowlist are configured | PASS | Backend tests/configured local env | Command and outbound paths are test-covered; do not expose token. |
| ChatPlace bot automations send external events | BLOCKED | Real bot test | User will build bots manually. |

## Current Checkpoint Notes

Update this section after each verified checkpoint.

| Date | Checkpoint | Commands / Checks | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-05-31 | Phase 1 reliability baseline | `python -m pytest backend -q`; `npm test -- --run`; `npm run lint`; `npm run build`; `npm run test:e2e` | PASS | Backend 101 passed, frontend 20 passed, lint clean, build passed with known bundle-size warning, e2e 1 passed. |
| 2026-05-31 | Landing-to-Telegram-to-CRM attribution links | `npm test -- --run src/lib/landingTracker.test.ts`; Playwright script against `/landing-tracker-example.html`; full backend/frontend/lint/build/e2e suite | PASS | Tracker now decorates Telegram `start` and CRM form query parameters with the same `visitor_id` and Meta attribution. Backend 102 passed, frontend 21 passed, lint/build/e2e passed. |
| 2026-06-01 | Bitrix stage discovery | `python -m pytest backend/test_bitrix_client.py backend/test_bitrix_api.py -q`; real `GET /api/crm/bitrix/stages` through TestClient | PASS | Real Bitrix returned 17 lead status labels. Stage mapping is deferred until sales team confirms meanings. |
| 2026-06-01 | Agent handoff packets | `python -m pytest backend/test_agent_orchestrator.py -q`; full backend/frontend/lint/build/e2e suite | PASS | Orchestrator responses now include structured `agentHandoffs` for campaign planning, Meta AI, execution fallback, monitoring, and specialist collaboration. |
| 2026-06-01 | Orchestrator output quality gate | `python -m pytest backend/test_agent_quality.py backend/test_agent_orchestrator.py -q`; full backend/frontend/lint/build/e2e suite | PASS | Orchestrator responses now include deterministic `quality` status/score/issues so thin outputs are flagged before campaign decisions. |
| 2026-06-01 | Monitoring recency readiness | `python -m pytest backend/test_monitoring_api.py -q`; stubbed manual monitoring run; full backend/frontend/lint/build/e2e suite | PASS | Monitoring now ignores stale campaigns whose latest metrics are more than seven days older than the freshest dashboard metric date; current manual run checked 1 snapshot and produced 1 relevant alert. |
| 2026-06-01 | Real-backend e2e reliability | `python -m pytest backend -q`; `npm test -- --run`; `npm run lint`; `npm run build`; `npm run test:e2e` | PASS | Playwright now starts FastAPI and asserts `/api/health` before dashboard checks. Chart containers use initial dimensions so e2e output is clean instead of hiding Recharts sizing warnings. |
| 2026-06-01 | Checklist and dashboard refactor plan | `python -m pytest --collect-only -q backend`; `npm test -- --run --reporter=verbose`; full gate from previous checkpoint | PASS | Checklist now reflects verified test coverage and blocked external dependencies. Added a safe `Dashboard.tsx` split plan for future UI work. |

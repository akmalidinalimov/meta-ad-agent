# Monitoring And Alerts

Date: 2026-05-30

## Purpose

The Monitoring Agent checks campaign health and warns before wasted spend grows. Version 0.5 starts with a manual run endpoint. Recurring four-hour automation should only be enabled after manual checks are reliable.

## Current Capability

- `POST /api/monitoring/run` runs one monitoring pass.
- `GET /api/monitoring/alerts` returns saved alerts from `storage/monitoring_alerts.json`.
- Dashboard data includes `monitoringAlerts`, and the Alerts tab shows the latest warnings.
- Telegram notifications are sent for `medium` and `high` severity alerts.

## Current Rules

The first rule set intentionally stays narrow:

- High severity: cost per lead rises by more than 35% while Telegram START rate falls by more than 25%.
- Medium severity: cost per click rises by more than 75%.
- Medium severity: Meta leads exist but Telegram START tracking is still zero, which means the agent cannot judge downstream lead quality.

The runner ignores completed historical campaigns when active/paused campaign metadata is available. This keeps monitoring focused on campaigns that can still affect current decisions.

These rules are not final strategy decisions. They are attention signals. The agent should explain why a metric may be moving and suggest two or three controlled next actions.

## Guardrails

- Monitoring cannot execute Meta changes.
- Monitoring can create alerts and recommendations only.
- Any pause, budget, placement, targeting, or creative action must become an approval request first.
- Recurring checks should not be enabled until the manual endpoint has been tested with real data.

## Manual Test

1. Run `POST /api/monitoring/run`.
2. Open the dashboard Alerts tab.
3. Confirm the alert appears in `GET /api/monitoring/alerts`.
4. Confirm Telegram receives a concise alert if Telegram credentials are configured.
5. Ask the Orchestrator what to do with the alert; it should propose approval-safe experiments or changes.

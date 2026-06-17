# Bitrix24 CRM Integration

Date: 2026-05-31

## Purpose

Bitrix24 closes the buyer-quality loop. Meta can tell us clicks and leads, but Bitrix24 can tell us whether a lead moved through sales stages, requested installment payment, paid partially, or paid in full.

## Current Implementation

The backend now includes:

- `GET /api/crm/bitrix/status`
- `POST /api/crm/bitrix/import`
- `GET /api/crm/bitrix/stages`
- `GET /api/crm/leads`
- `GET /api/crm/funnel?days=N&entity=lead|deal` — per-audience × per-CRM-stage matrix (read-only)
- normalized CRM lead storage in `storage/crm_leads.json`

## Per-audience funnel (`GET /api/crm/funnel`)

Read-only, additive endpoint. For each Bitrix lead (or deal, with `?entity=deal`) it reads the
current stage, **joins to a ChatPlace bot-start by phone** (trailing-9-digit match, then
`@username`, then `utm_content` as a cross-check) and **inherits that bot-start's audience**
(`aud`). It returns the count at every discovered stage per audience (`ai`/`business`/`it`/
`original`/`content`), plus an honest `unattributed` bucket and a `matchRate`. Audiences are
captured at bot-start via the enriched START webhook (`aud`, `phone`, `username`); until that
webhook is flowing, all leads land in `unattributed` (matchRate 0) — by design, never hidden.

- **Paid stage:** stages are discovered live (`crm.status.list`); the terminal "Paid" stage(s)
  are taken from `BITRIX_PAID_STATUS_IDS` (comma-separated, authoritative) or guessed from
  stage-label keywords. The response exposes `paidStageIds` so the choice is auditable.
- **Dashboard:** the React dashboard renders this matrix only when the frontend build has
  `VITE_CRM_ENABLED=true` (a feature flag), so a half-configured CRM never reaches the live UI.

Imported leads preserve:

- CRM lead ID
- CRM stage/status
- phone
- visitor ID
- Telegram user ID/username when available
- UTM source, medium, campaign, content, term
- raw Bitrix24 payload for future mapping

Stage discovery uses the Bitrix24 REST method `crm.status.list` with the lead status entity `STATUS`. This lets the agent copy the CRM's real stage IDs and labels before any buyer-quality mapping is created.

Example stage discovery response:

```json
{
  "ok": true,
  "entityId": "STATUS",
  "stages": [
    {
      "statusId": "NEW",
      "name": "Ne obrabotinniy"
    },
    {
      "statusId": "CONVERTED",
      "name": "Qualified lead"
    }
  ]
}
```

Do not hardcode normalized sales stages yet. First fetch the real Bitrix stages, confirm them with the sales team, then map them later into buyer-quality categories.

## Required Credentials

The webhook key alone is not enough. Bitrix24 REST calls need either:

```text
BITRIX24_WEBHOOK_URL=https://your-portal.bitrix24.xx/rest/user_id/webhook_key/
```

or all three parts:

```text
BITRIX24_PORTAL_URL=https://your-portal.bitrix24.xx
BITRIX24_USER_ID=1
BITRIX24_WEBHOOK_KEY=...
```

The webhook key has been stored locally if provided, but the real import cannot run until the portal URL and user ID, or the full webhook URL, are configured.

## Sales Team Requirement

Ask the outsourced sales team to preserve these fields on the CRM form or lead:

- `visitor_id`
- `telegram_user_id`
- `telegram_username`
- `telegram_bot_id`
- `segment`
- `vsl_id`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `utm_term`

Without these fields, the agent can count CRM leads but cannot reliably join them back to campaign, ad set, creative, Telegram bot, or VSL.

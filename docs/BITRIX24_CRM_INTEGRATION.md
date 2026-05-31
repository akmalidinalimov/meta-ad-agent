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
- normalized CRM lead storage in `storage/crm_leads.json`

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

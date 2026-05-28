# Funnel Event Tracking

Date: 2026-05-28

## Purpose

Meta tells us clicks, spend, and lead actions. It does not tell us whether a person became a high-quality Telegram subscriber, watched the VSL sequence, clicked the CRM form, or became a buyer. This event layer closes that gap.

The backend now accepts attribution-rich funnel events at:

```http
POST /api/funnel/events
```

Summary endpoint:

```http
GET /api/funnel/summary
```

Events are stored locally in:

```text
storage/funnel_events.jsonl
```

## Event Names

Supported event names:

- `landing_view`
- `vsl_button_click`
- `telegram_link_click`
- `bot_start`
- `vsl_sequence_started`
- `vsl_key_message_sent`
- `form_button_click`
- `form_opened`
- `crm_form_submit`
- `qualified_lead`
- `partial_payment`
- `full_payment`

## Required Attribution Fields

Send as many of these as possible:

- `visitor_id`
- `telegram_user_id`
- `segment`
- `vsl_id`
- `landing_page_id`
- `telegram_bot_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `utm_term`
- `fbclid`

## Landing Page Payload Example

Use this when a user lands on the page:

```json
{
  "event": {
    "event_name": "landing_view",
    "visitor_id": "visitor_abc123",
    "segment": "income",
    "vsl_id": "income_vsl_01",
    "landing_page_id": "income_lp_01",
    "campaign_id": "{{campaign.id}}",
    "adset_id": "{{adset.id}}",
    "ad_id": "{{ad.id}}",
    "creative_id": "{{creative.id}}",
    "utm_source": "meta",
    "utm_medium": "paid",
    "utm_campaign": "{{utm_campaign}}",
    "utm_content": "{{utm_content}}",
    "fbclid": "{{fbclid}}"
  }
}
```

When the user clicks the button to Telegram, send:

```json
{
  "event": {
    "event_name": "telegram_link_click",
    "visitor_id": "visitor_abc123",
    "segment": "income",
    "vsl_id": "income_vsl_01",
    "landing_page_id": "income_lp_01",
    "telegram_bot_id": "income_bot",
    "campaign_id": "{{campaign.id}}",
    "adset_id": "{{adset.id}}",
    "ad_id": "{{ad.id}}",
    "creative_id": "{{creative.id}}",
    "fbclid": "{{fbclid}}"
  }
}
```

## Telegram / ChatPlace Payload Examples

When the user clicks START:

```json
{
  "event": {
    "event_name": "bot_start",
    "visitor_id": "{{visitor_id}}",
    "telegram_user_id": "{{telegram_user_id}}",
    "segment": "income",
    "vsl_id": "income_vsl_01",
    "telegram_bot_id": "income_bot",
    "campaign_id": "{{campaign_id}}",
    "adset_id": "{{adset_id}}",
    "ad_id": "{{ad_id}}",
    "creative_id": "{{creative_id}}",
    "fbclid": "{{fbclid}}"
  }
}
```

When the 20-minute key message is sent:

```json
{
  "event": {
    "event_name": "vsl_key_message_sent",
    "visitor_id": "{{visitor_id}}",
    "telegram_user_id": "{{telegram_user_id}}",
    "segment": "income",
    "vsl_id": "income_vsl_01",
    "telegram_bot_id": "income_bot"
  }
}
```

When the user clicks the CRM form button:

```json
{
  "event": {
    "event_name": "form_button_click",
    "visitor_id": "{{visitor_id}}",
    "telegram_user_id": "{{telegram_user_id}}",
    "segment": "income",
    "vsl_id": "income_vsl_01",
    "telegram_bot_id": "income_bot",
    "campaign_id": "{{campaign_id}}",
    "adset_id": "{{adset_id}}",
    "ad_id": "{{ad_id}}",
    "creative_id": "{{creative_id}}"
  }
}
```

## Bitrix24 Form URL

The Telegram form button should open the Bitrix24 form with preserved attribution:

```text
https://inafform.bitrix24.site/crm_form_vospb/
?visitor_id={{visitor_id}}
&telegram_user_id={{telegram_user_id}}
&segment=income
&vsl_id=income_vsl_01
&telegram_bot_id=income_bot
&campaign_id={{campaign_id}}
&adset_id={{adset_id}}
&ad_id={{ad_id}}
&creative_id={{creative_id}}
&utm_source=meta
&utm_medium=paid
&fbclid={{fbclid}}
```

## First Quality Metrics This Enables

- Telegram START rate = `bot_start / telegram_link_click`
- Key message reach rate = `vsl_key_message_sent / bot_start`
- Form click rate = `form_button_click / vsl_key_message_sent`
- Segment quality = downstream events per segment
- Creative quality = downstream events per creative ID

## Rule

Do not scale a campaign only because Meta CPL is cheap. Scale only when funnel events show that the segment and creative produce quality Telegram and CRM actions.

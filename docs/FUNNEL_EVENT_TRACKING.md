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

The preferred setup is to install the shared tracker script on every landing page. This script creates a stable `visitor_id`, sends `landing_view`, rewrites Telegram links with `?start=<visitor_id>`, and sends `telegram_link_click`.

```html
<script>
  window.MetaAdAgentTracker = {
    endpoint: "https://YOUR_AGENT_BACKEND/api/funnel/events",
    segment: "income",
    vslId: "income_vsl_01",
    landingPageId: "income_lp_01",
    telegramBotId: "income_bot",
    telegramSelector: "[data-meta-agent-telegram]"
  };
</script>
<script src="https://YOUR_LANDING_DOMAIN/landing-tracker.js"></script>

<a href="https://t.me/YOUR_BOT" data-meta-agent-telegram>
  Watch the free video
</a>
```

For local testing, open:

```text
http://127.0.0.1:5173/landing-tracker-example.html
```

For production landing pages, add every landing-page origin to the backend environment:

```env
FUNNEL_ALLOWED_ORIGINS=https://income.example.com,https://business.example.com,https://creators.example.com
```

The tracker intentionally sends only the `visitor_id` in Telegram's `start` parameter. Telegram start payloads are short, so full attribution stays in the backend events instead of being packed into the Telegram link.

Use this manual payload shape if a page builder cannot load the tracker script:

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

ChatPlace supports External API requests inside automations. In each Telegram bot automation, add an `Action` block and choose `External request`. Use:

```text
POST https://YOUR_AGENT_BACKEND/api/chatplace/events
Content-Type: application/json
```

If you set `CHATPLACE_WEBHOOK_SECRET` in the backend environment, add either:

```http
x-chatplace-secret: YOUR_SHARED_SECRET
```

or include `"secret": "YOUR_SHARED_SECRET"` in the JSON body.

Create/reuse these ChatPlace variables:

- `visitor_id`
- `segment`
- `vsl_id`
- `landing_page_id`
- `telegram_bot_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `fbclid`

Use ChatPlace profile variables where available:

- `{{ username }}`
- `{{ fullName }}`
- `{{ chatLink }}`

Important: ChatPlace documentation confirms variables can store client data and be passed to external systems, and External request actions can send JSON/form data to any API. The only uncertain part is whether your ChatPlace Telegram start trigger exposes the deep-link payload directly as a variable. To make setup resilient, this backend accepts any of these fields and extracts the visitor ID:

- `visitor_id`
- `start_payload`
- `message_text` like `/start v_xxxxx`
- a Telegram link like `https://t.me/bot?start=v_xxxxx`

When the user clicks START, add an External request near the beginning of the automation:

```json
{
  "event_name": "bot_start",
  "visitor_id": "{{ visitor_id }}",
  "start_payload": "{{ visitor_id }}",
  "telegram_user_id": "{{ chatLink }}",
  "telegram_username": "{{ username }}",
  "telegram_full_name": "{{ fullName }}",
  "segment": "income",
  "vsl_id": "income_vsl_01",
  "landing_page_id": "income_lp_01",
  "telegram_bot_id": "income_bot",
  "campaign_id": "{{ campaign_id }}",
  "adset_id": "{{ adset_id }}",
  "ad_id": "{{ ad_id }}",
  "creative_id": "{{ creative_id }}",
  "fbclid": "{{ fbclid }}"
}
```

The backend response includes fields ChatPlace can map back into variables:

```json
{
  "ok": true,
  "tracking_status": "saved",
  "visitor_id": "v_xxxxx",
  "event_name": "bot_start",
  "telegram_user_id": "..."
}
```

If ChatPlace exposes the raw `/start` message instead of a clean variable, use:

```json
{
  "event_name": "bot_start",
  "message_text": "{{ message }}",
  "telegram_username": "{{ username }}",
  "telegram_full_name": "{{ fullName }}",
  "segment": "income",
  "vsl_id": "income_vsl_01",
  "landing_page_id": "income_lp_01",
  "telegram_bot_id": "income_bot"
}
```

If ChatPlace cannot expose the deep-link payload at all, keep the `bot_start` request anyway and send `telegram_user_id`/`username`; the dashboard will count Telegram starts, but they will be unattributed until ChatPlace variable mapping is fixed.

When the VSL sequence starts:

```json
{
  "event_name": "vsl_sequence_started",
  "visitor_id": "{{ visitor_id }}",
  "telegram_user_id": "{{ chatLink }}",
  "telegram_username": "{{ username }}",
  "telegram_full_name": "{{ fullName }}",
  "segment": "income",
  "vsl_id": "income_vsl_01",
  "telegram_bot_id": "income_bot"
}
```

When the 20-minute key message is sent:

```json
{
  "event_name": "vsl_key_message_sent",
  "visitor_id": "{{ visitor_id }}",
  "telegram_user_id": "{{ chatLink }}",
  "telegram_username": "{{ username }}",
  "telegram_full_name": "{{ fullName }}",
  "segment": "income",
  "vsl_id": "income_vsl_01",
  "telegram_bot_id": "income_bot"
}
```

When the user clicks the CRM form button:

```json
{
  "event_name": "form_button_click",
  "visitor_id": "{{ visitor_id }}",
  "telegram_user_id": "{{ chatLink }}",
  "telegram_username": "{{ username }}",
  "telegram_full_name": "{{ fullName }}",
  "segment": "income",
  "vsl_id": "income_vsl_01",
  "telegram_bot_id": "income_bot",
  "campaign_id": "{{ campaign_id }}",
  "adset_id": "{{ adset_id }}",
  "ad_id": "{{ ad_id }}",
  "creative_id": "{{ creative_id }}"
}
```

ChatPlace can map variables from API responses. If the first `bot_start` request returns `visitor_id`, map it back into the ChatPlace variable `visitor_id` so later automation steps use the same value.

The older generic funnel endpoint also works if you prefer wrapping the event under `"event"`:

```json
{
  "event": {
    "event_name": "bot_start",
    "visitor_id": "{{ visitor_id }}",
    "telegram_user_id": "{{ chatLink }}",
    "telegram_username": "{{ username }}",
    "telegram_full_name": "{{ fullName }}"
  }
}
```

## ChatPlace Testing Checklist

Before running traffic:

- Open the landing page with test UTM parameters.
- Click the Telegram button and confirm `/api/funnel/summary` shows one `telegram_link_click`.
- In ChatPlace, click `Test request` on the first External request.
- Confirm `/api/funnel/summary` shows one `bot_start`.
- Confirm `telegramStartRate` appears in `rates`.
- Continue to the 20-minute block and form button block with test users.
- If `bot_start` appears but attribution is missing, inspect the saved event and adjust which ChatPlace variable is sent as `visitor_id` or `message_text`.

Example summary response:

```json
{
  "totalEvents": 3,
  "eventsByName": {
    "telegram_link_click": 1,
    "bot_start": 1,
    "vsl_key_message_sent": 1
  },
  "rates": {
    "telegramStartRate": 100,
    "keyMessageReachRate": 100,
    "formClickRate": 0,
    "qualifiedLeadRate": 0,
    "fullPaymentRate": 0
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

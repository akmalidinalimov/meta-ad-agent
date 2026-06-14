# ChatPlace + Bitrix24 capabilities for full-funnel measurement

_Researched 2026-06-13 (deep-research workflow, 205 verified claims, official docs). Sources: help.chatplace.io, apidocs.bitrix24.com, helpdesk.bitrix24.com. All claims survived 3-vote adversarial verification (zero refuted)._

## Funnel & KPIs we measure

Instagram/Facebook ad → landing page → Telegram bot (ChatPlace) → VSL → daily messages → Bitrix CRM form → CRM stages → paid.

| KPI | Measurable | How |
|---|---|---|
| Ad link clicks | ✅ | Meta API (already pulled) |
| Visit rate = landing / clicks | ✅ | `landing_view` (tracker) ÷ Meta link clicks |
| Lead rate = TG-click / landing | ✅ | `telegram_link_click` ÷ `landing_view` |
| START rate = start / TG-click | ✅ per **campaign** | `bot_start` ÷ `telegram_link_click`; per-visitor join not possible (see ChatPlace ceiling) |
| VSL watch rate | ⚠️ proxy | `vsl_watched` from "I watched ▶" button ÷ `bot_start` (real % only if VSL self-hosted) |
| Daily-message button CTR | ✅ | ChatPlace native % + External request per button |
| CRM rate = submit / form-click | ✅ | `form_button_click` (bot) → Bitrix hidden-field capture on submit |
| Stage progression, **paid + amount** → ROAS | ✅ | `ONCRMDEALUPDATE` → read `STAGE_ID`+`OPPORTUNITY` |

**Ceiling:** only real VSL watch-depth (proxy unless self-hosted) and per-**visitor** START attribution (degrades to per-**campaign**). Everything from the form onward is fully measurable with revenue amounts → true ROAS.

## ChatPlace (Telegram bot builder)

- **Deep-link `?start=<id>`: NOT readable as a variable.** No documented way to read an arbitrary per-click start payload. Only **pre-created static referral links** that stamp a fixed tag/variable on every clicker; `{{referralCode}}` exists only for referral links. → **Decision: one referral link per ad campaign**, stamping `campaign_id`.
- **External API request action: yes.** GET/POST/PUT/PATCH/DELETE, inserts variables into body/headers, maps response back into variables (two-way). One of 17 actions. Can fire from any step/button. Failure handling = tag-on-error branching only; **no documented retries or rate limits**.
- **Native analytics: per-block reach counts, per-button click-%, "Record conversion" nodes** (dedup'd per user). Display-only, **no export/API**.
- **VSL: no video-view tracking.** Proxy (button / timed gate) or self-host.
- **Native Bitrix24 integration: yes** — "Send data to CRM" (Отправить данные в CRM) action maps variables → Bitrix **deal** fields, can create custom fields from the UI. Modes: create deal / update existing. Requires **PRO** + connected channel; Bitrix must also be on a paid plan.
- **Plans:** Free = 200 contacts/mo, 1 bot, branding — unusable for ads. **PRO ($20/mo, 7-day trial)** unlocks External requests, CRM integration, payment, automation links, unlimited interactions (1 bot; +$20/extra). Premium $250/mo. *(Exact gating of "External request" not in the pricing table — confirm in-app, but feature docs imply PRO.)*

## Bitrix24 CRM

- **Capture arbitrary URL params into deal fields: yes — key enabler.** Hidden fields → **Expert mode → "Hidden field values" tab → "Parameter" source**; append `?param=XXX` to the form link, value saves into the mapped CRM field. No documented plan gate or param-count limit. (Standard 5 UTMs auto-capture with no config.) Also auto-captures domain/page/form-ID without params.
- **Outbound webhook `ONCRMDEALUPDATE`:** fires on any deal update, `crm` scope, any user can subscribe. **Payload = deal ID only** → must call back to read fields. Verified via `application_token` (not guaranteed present if action isn't tied to a user). Queued (`ts` timestamp) → possible lag. **No documented retry policy.**
- **Inbound REST webhook:** static URL, **key never expires**, no OAuth refresh. `crm.item.get` (use this; `crm.deal.get` deprecated) returns `STAGE_ID`, `OPPORTUNITY` (amount), `UF_CRM_*` custom fields. **REST is paid-plan only.**
- **Paid-stage detection:** `STAGE_ID` + `OPPORTUNITY`; native "Track invoice payment" / "Track order payment" triggers move the deal to a stage + leave a timeline footprint.
- **Rate limits:** leaky bucket 2 req/s, burst 50 (most plans) / 5 & 250 (Enterprise); per **IP**; HTTP 503 `QUERY_LIMIT_EXCEEDED` over limit; `batch` = 50 calls in one; per-method 480s/10min cap. Comfortable at course volume.
- **Caveat:** `onCrmDealMoveToCategory` (pipeline change) is **NOT** available via outbound webhook — only stage moves *within* a pipeline arrive as `ONCRMDEALUPDATE`. → **Use a single pipeline.**

## What already exists in our backend (extend, don't rebuild)

`landingTracker.ts` (visitor_id, link rewrite, form decoration), `POST /api/funnel/events` + `/api/chatplace/events` + `GET /api/funnel/summary`, `bitrix_client.py` (read + `UF_CRM_*` normalization), `crm_store.py`, funnel↔CRM join, per-(campaign,date) START join → `DailyAdMetric.telegramSubscribers`. Gaps: rates are global-only; no Bitrix inbound webhook receiver; payment amounts not surfaced as ROAS; no dedup / JSONL rotation / TZ-offset fix.

# Per-campaign START attribution — implementation plan

- **Date:** 2026-06-17
- **Status:** scoped, not started
- **Related:** PR #12 (first-party START rate), `meta-ad-agent-dashboard-state` memory, `meta-funnel-tracker` skill (Tier 2)

## Goal

Make the dashboard START rate attributable to a **single campaign**, not just account-wide.

Today (post PR #12) START rate = first-party Telegram bot-starts ÷ button clicks, computed
**account-wide**, because `bot_start` events carry no `campaign_id` (verified on prod: 1,630
bot-starts, 0 with a `campaignId`). `campaign_kpis` already has a campaign-scoped branch, but it
never fires because `telegram_starts_by_campaign_date()` is always empty.

## Why there is a blocking prerequisite

`campaign_kpis` ([backend/routers/campaigns.py:149-162](../../../backend/routers/campaigns.py)) has a
**latent denominator-scope bug** that is *dormant only because attribution doesn't work yet*. The
attribution work below is exactly what arms it. So the fix must land first.

When a campaign is scoped **and** has attributed starts (`campaign_starts > 0`), the code swaps the
numerator to that campaign's starts but leaves the denominator (`link_clicks`) **account-wide** — it
is computed once via `count_event_users("telegram_link_click", ...)` and never re-scoped. Dividing
one campaign's starts by *all* campaigns' button clicks understates the rate badly, with no warning.
Separately, `telegram_starts_by_campaign_date()` is a raw `Counter` (`+= 1` per event, **not**
user-deduped), while the account path's `count_bot_starts` dedupes by user — so even at equal scope
the two can disagree (a repeat-starter overstates the scoped rate).

---

## Phase 0 — Fix the denominator-scope bug (BLOCKING, do first)

Land this **before** any attribution change.

- Make the START **denominator** campaign-scoped whenever the **numerator** is. Verify whether
  `telegram_link_click` funnel events already carry `campaign_id` (the landing tracker knows it from
  the ad URL, so they likely do). If yes, add a `telegram_link_clicks_by_campaign_date()` helper in
  `funnel_events.py` mirroring `telegram_starts_by_campaign_date()`, and use it for the scoped
  denominator. If `telegram_link_click` does **not** carry `campaign_id`, the scoped denominator
  isn't possible — in that case keep the rate account-wide rather than mix scopes.
- Make the scoped numerator **user-deduped** to match the account path (dedupe
  `telegram_starts_by_campaign_date` by `telegramUserId` / `visitorId` instead of a raw `Counter`).
- **Invariant:** never display a campaign-scoped numerator over an account-wide denominator. Until
  both can be scoped consistently, force `startScope = "account"` and keep the "· account-wide"
  label. The label must be honest about scope at all times.
- Tests (`backend/test_campaigns_api.py`): scoped campaign with attributed starts → campaign
  numerator ÷ campaign denominator; repeat-starter is deduped; falls back to account scope (with
  the label) when the campaign has no attributed clicks.

## Phase 0.5 — Spike: can ChatPlace relay the start payload? (BLOCKING)

The real unknown (per the `meta-funnel-tracker` skill: ChatPlace does not cleanly expose the raw
`?start=` payload). No point building Phases 1–2 until confirmed.

- Configure ChatPlace's START trigger (External Request / HTTP action) to POST the start param to
  `/api/chatplace/events`.
- Send a test deep-link `?start=test123`, confirm the webhook receives `test123`.
- If it can't relay → stay account-wide (Phase 0 already makes that correct and honest), or evaluate
  a platform with native ref support (ManyChat/SendPulse). If it can → proceed.

## Phase 1 — Carry campaign_id in the deep link without breaking VSL routing

- Confirm the ad URL passes `{{campaign.id}}` to the landing page.
- Update `landing-tracker.js` to pack `campaign_id` into the start payload alongside the existing
  VSL route, e.g. `?start=vsllp__c<campaign_id>` (stay within Telegram's 64-char, `[A-Za-z0-9_-]`
  limit; the VSL router must tolerate the suffix).
- Bump the tracker to `?v=4`, deploy to Lovable, verify VSL routing still works and the payload
  carries `campaign_id`. (Deploy discipline: the prod tracker is content-checked by md5; never
  overwrite without verifying.)

## Phase 2 — Backend extracts + attributes

- `normalize_chatplace_event` parses `campaign_id` out of the relayed start payload and writes it
  onto the `bot_start` funnel event.
- `telegram_starts_by_campaign_date` then aggregates real per-campaign starts; `campaign_kpis`'s
  scoped branch lights up — and because **Phase 0 already scoped the denominator and dedup**, the
  per-campaign START rate is correct, not the understated/overstated number the dormant bug would
  have produced. The "· account-wide" label drops off for campaigns that have attributed starts.

## Phase 3 — Reconcile the third START formula (recommended)

The Telegram KPI digest (`telegram_digest.py` → `build_funnel_summary().rates.telegramStartRate`)
uses a **third** START formula (visitorId-deduped only, no Meta fallback), so the digest can already
report a START number that won't reconcile with the dashboard. Point the digest at
`select_start_rate` so digest and console agree by construction.

## Phase 4 — Verify

- Pick a campaign with attributed starts → START shows its own rate (campaign numerator ÷ campaign
  denominator), no "· account-wide" caveat.
- Pick a campaign without attribution → falls back to account scope with the honest label.
- Digest and dashboard report the same START rate for the same account/window.

## Risk map

- All the risk is concentrated in **Phase 0.5** (ChatPlace relay). Phase 0 is a pure backend
  correctness fix with no external dependency and is worth doing on its own merit.
- Phase 0 must precede Phase 2, or Phase 2 ships a wrong, decision-load-bearing per-campaign rate.

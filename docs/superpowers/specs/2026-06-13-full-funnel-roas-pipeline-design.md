# Full-Funnel ROAS Pipeline — Design Spec

**Date:** 2026-06-13
**Status:** Draft for operator review (post red-team)
**Branch target:** new `feat/roas-pipeline` off `feat/rbac-roles`
**Research:** `docs/research/2026-06-13-chatplace-bitrix-capabilities.md` (205 verified claims)
**Red-team:** adversarial design review, 67 findings → adjudicated against worktree code (two "criticals" were stale-checkout false positives; see §9)

## 1. Goal

Make the agent **revenue-aware**. Today it sees leads + Telegram STARTs and optimizes for cheap CPL. This pipeline measures the full funnel (ad → landing → Telegram bot → VSL → daily messages → Bitrix CRM form → CRM stages → paid) and feeds real **per-campaign ROAS** into analysis, the Monitor KPI rail, and the autonomous scaler — so the agent scales *buyers*, not cheap leads.

## 2. Decisions (locked)

- **START attribution: per-campaign**, via one pre-created ChatPlace referral link per ad campaign that stamps `campaign_id`. ChatPlace cannot read a per-click `?start=` payload, so per-visitor attribution ends at the landing→bot handoff. Landing-side stays per-visitor; bot/CRM-side is per-campaign.
- **VSL: proxy now**, self-host later. An "I watched ▶" button emits `vsl_watched` (a self-reported engagement flag, **not** a watch-completion rate). Real watch-depth deferred to a self-hosted page.
- **Single Bitrix pipeline** (pipeline-change events aren't available via webhook).

## 3. Core architectural principle (from red-team)

**CRM state is authoritative; the event tape is not.** The single biggest class of bugs (revenue double-counting on every deal edit, poller/webhook overlap, retry re-delivery, refunds never reversed) all dissolve if revenue is derived from a **dealId-keyed state table** rather than by summing webhook deliveries.

### 3.1 Deal-state table (`backend/deal_state_store.py`, new)

`storage/deal_state.json`, keyed by `dealId`:
```json
{ "dealId": "123", "stageId": "WON", "amountRaw": 1500000, "currency": "UZS",
  "amountUsd": 118.0, "fxRate": 12700, "fxDate": "2026-06-13",
  "campaignId": "cmp_ai_may", "telegramUserId": "...", "firstSeenAt": "...",
  "enteredPaidAt": "2026-06-12T...", "updatedAt": "..." }
```
- **Both** the outbound webhook **and** the fallback poller `upsert` this table (last-write-wins on current `STAGE_ID` + `OPPORTUNITY`). Neither appends revenue events directly.
- A `full_payment` funnel event is emitted **only on a forward transition into the paid stage** not previously recorded for that `dealId` (idempotent).
- On transition **out** of the paid stage (refund/downgrade), the deal's revenue contribution drops to zero — ROAS is **not** monotonic.
- `purchaseRevenueUsd` for a campaign-day is derived from the **current set of paid deals**, never by summing deliveries.

## 4. Identity domains & rate model (from red-team)

Two explicit measurement domains, joined **only** at campaign granularity — never chain a per-visitor denominator into a per-bot-user numerator:

| Domain | Key | Stages |
|---|---|---|
| Landing | `visitorId` (per device/session) | `landing_view`, `telegram_link_click` |
| Bot/CRM | `telegramUserId` (COALESCE with visitorId) | `bot_start`, `vsl_watched`, `form_button_click`, `crm_form_submit`, `qualified_lead`, `full_payment` |

- The landing→bot handoff is presented as **one labeled bridge rate** ("START rate, campaign-level"), not a continuous chain.
- Top-of-funnel is labeled **"sessions/devices"**; bot/CRM stages **"people"**.
- `eventSteps` is rendered from an ordered **CANONICAL_EVENTS manifest** (missing canonical events show `status:"never_seen", count:0`), ordered by the fixed sequence, **not** by arrival order.
- Replace the silent `min(100, rate)` clamp: if a later stage's actor set isn't a subset of the prior stage's, flag `attribution_inconsistent` and warn (clamp for **display only**, never for the value used in ranking). Invariant check: a later step must never out-number an earlier one.
- `unattributedActors` count + a data-quality banner when the no-id fraction exceeds a threshold.
- Per-campaign rates only **below** campaign granularity is suppressed (no per-creative/adset ROAS on bot/CRM events); null-`campaignId` "Unknown" bucket is flagged, **never ranked**.

## 5. Revenue correctness (from red-team)

- **Currency:** read `CURRENCY_ID` from `crm.item.get`; store `amountRaw` + `currency` + `amountUsd` with a **dated, pinned FX rate** (per-deal at payment time, stored for deterministic re-runs). Unknown currency → `amountUsd=null`, excluded from ROAS. **Sanity ceiling:** ROAS > 50× flags a likely unit error.
- **Booked vs collected:** ROAS uses **booked** contract value, counted **once** on the first paid transition (never re-added on later `OPPORTUNITY` edits). Partial payments are a funnel-progress flag, excluded from revenue (documented; not summed with `full_payment`).
- **Trailing-window ROAS:** compute campaign ROAS over a rolling window (campaign-lifetime or last-N-days), **not** a single day-matched key — a buyer who clicks May 1 and pays May 15 must not orphan revenue from spend. Label the lag.
- **Three-clock normalization:** normalize Bitrix portal TZ, server UTC, and Meta ad-account TZ all to the **Meta ad-account timezone** before bucketing (extends the existing UTC-vs-Meta fix to add the Bitrix clock).
- **Trust tier / min-buyer gate:** gate the ROAS KPI on known currency + deduped deals + a **minimum buyer count**; below threshold, show "revenue tracking warming up" and keep ranking on lead/Telegram quality. Smooth/regularize per-campaign ROAS toward the account mean by sample size so one whale deal can't flip the ranking. Surface revenue concentration (top deal as % of campaign revenue) and buyer count beside revenue. If the top-ranked campaign changes on a single new deal, flag the ranking low-confidence.
- **Evergreen-link / paused-campaign guard:** before crediting per-campaign revenue, verify the campaign had nonzero spend in a plausible click→pay window (Meta insights already fetched). Revenue from long-paused campaigns' still-circulating links → a separate "residual/evergreen" bucket, excluded from active-campaign ROAS ranking.
- **Returning vs new:** START/buyer numerators are **first-seen-per-`telegramUserId`** within the window; repeat `bot_start` → `returning_start`, excluded from acquisition rates. CRM deals deduped per (`telegramUserId`/phone); a second deal from a known contact is expansion, not acquisition.

## 6. Security & robustness hardening (from red-team, confirmed in code)

- **Ingest auth model:** `/api/funnel/events`, `/api/chatplace/events`, and the new `/api/bitrix/webhook` are **public to the cookie session-guard but each carry their own header secret**. Add an explicit ingest-allowlist to `_AUTH_PUBLIC_PATHS`-style handling so secret-authenticated machine callers (landing page, ChatPlace, Bitrix) work without a dashboard cookie. *(Today funnel endpoints sit behind the cookie guard, which would block external posters when `DASHBOARD_SESSION_AUTH=true` — make this explicit.)*
- **Fail CLOSED:** every secret/token check rejects when the expected secret is **unconfigured** (today `if expected_secret and ...` at `funnel.py:27` fails open). Assert required secrets at startup. Use `hmac.compare_digest`. Accept secrets via **header only**, never request body (the body lands in logs / raw passthrough).
- **`extract_visitor_id`:** return `None` (not `text[:64]`, `chatplace_events.py:112`) on `VISITOR_ID_PATTERN` mismatch; drop the `message_text`/`text`/`trigger` fallbacks; accept `visitor_id` only from an explicit structured variable. Route the referral payload to `campaign_id`, validated against the known active-Meta-campaign set.
- **Reject browser-origin payment events:** `/api/funnel/events` must reject `full_payment`/`qualified_lead`/`crm_form_submit` from browser origins — those come only from the authenticated Bitrix webhook.
- **Bitrix webhook:** authenticate before **any** `crm.item.get` callback (fail-closed secret PATH/header independent of `application_token`, since the token isn't guaranteed present); coalesce/debounce duplicate deal IDs; outbound token-bucket well under 2 req/s so forged traffic can't starve real lookups or trip `QUERY_LIMIT_EXCEEDED`. The authenticated **poller is the source of truth**; a dropped or forged push can neither fabricate nor lose revenue.
- **PII:** do **not** store the raw CRM row (`bitrix_client.py:112`) or raw unmapped payload in funnel events; persist only `dealId` + stage + amount + currency + campaign field + telegramUserId. Strip phone/name/email before persistence; `/api/funnel/summary` and `/api/crm/leads` never return PII to the dashboard.
- **Decouple ingest from aggregation:** ingest endpoints return `{ok:true}` immediately and **never** call `build_funnel_summary` in the request path (today it rescans the whole file on every ingest + GET); summaries compute lazily on GET, cached on file mtime. The webhook returns 200 fast (enqueue, process async) so a slow build can't cause a dropped delivery.
- **Storage:** JSONL rotation/retention (or migrate to SQLite WAL with a unique index on the dedup key); single-writer lock for multi-writer append (webhook + poller + chatplace) on the Windows host; count + alert on parse failures instead of silently dropping lines.

## 7. Operability & self-test (from red-team)

A non-technical operator wires ~16 config points across 3 vendor UIs with no feedback loop. Silent-failure guards:
- `eventSteps` from the canonical manifest (a forgotten External request shows as `never_seen`, not a misattributed neighbor).
- Startup + daily check that the configured Bitrix paid stage ID exists (`fetch_bitrix_statuses`); alert if `qualified_lead`s accrue with **zero** `full_payment`s (wrong stage ID or broken mapping).
- **Attribution-coverage metric:** % of new `crm_form_submit`/`qualified_lead` carrying a non-empty, recognized `campaign_id`; alert if it drops over a trailing window (catches a broken bot→CRM field mapping within hours).
- **Capacity vs quality alert:** `telegram_link_click` steady but `bot_start` near-zero ⇒ likely ChatPlace contact-cap/outage, **not** a creative problem — quarantine those days from ROAS and **never** let the agent pause/scale on them.
- `POST /api/funnel/selftest` emits a tagged synthetic event + green/red end-to-end checklist; synthetic/test events carry `isTest` and are excluded from all rates/KPIs/ranking.
- **Test-traffic isolation:** stamp every event with `source` + `isTest` (test-actor Telegram IDs/phones, reserved test `campaign_id`, selftest tag); exclude from production metrics; dev/test server uses a separate storage path.
- Watch-engine fix (pre-existing `campaign_watch.py`): compare **trailing windows**, not `dates[-1]` vs `dates[-2]`; require min absolute lead/buyer counts in both windows; skip/ widen across date gaps. Apply the same min-denominator gate the ranking uses.

## 8. Build phases (ordering enforced by dependencies)

| Phase | Scope | Gates |
|---|---|---|
| **0 — Security & storage foundations** | Fail-closed secrets + startup asserts; ingest auth model; `extract_visitor_id` hardening; reject browser-origin payment events; PII stripping; JSONL rotation + single-writer + parse-failure alerts; decouple ingest from aggregation. **Must precede the webhook.** | No external deps |
| **1 — Two-domain rates** | Canonical-manifest `eventSteps`; per-visitor vs per-telegramUser domains; `attribution_inconsistent` flag replacing clamp; per-campaign rates + null-bucket suppression + denominator display; `unattributedActors`; returning-vs-new. | No external deps |
| **2 — Bitrix read enrichment** | `crm.item.get` for `STAGE_ID`+`OPPORTUNITY`+`CURRENCY_ID`+`UF_CRM_*`; stage-ID config (qualified/paid); rate-limit-safe client (batch, token-bucket). | Bitrix read access |
| **3 — Deal-state table + webhook + poller** | `deal_state_store`; `POST /api/bitrix/webhook` (fail-closed auth, debounce, async); authoritative poller; forward-transition `full_payment` emission; refund reversal; evergreen/paused guard; campaign_id validation. | Bitrix outbound webhook |
| **4 — ROAS wiring + dashboard** | Currency conversion + pinned FX; trailing-window ROAS; 3-clock normalization; trust tier + min-buyer + smoothing; 6th Monitor KPI (ROAS/CPA, provisional labeling); analysis-engine revenue ranking; **LIVE-path regression test with seeded events**. | Phases 2–3 |
| **5 — Operator runbook + self-tests** | Step-by-step ChatPlace PRO + referral-link-per-campaign + External requests + Send-to-CRM; Bitrix Expert-mode hidden fields + webhooks + single pipeline; landing tracker; selftest endpoint; health/coverage/capacity alerts; campaign→referral-link registry. | Parallel; operator-side |

## 9. Red-team adjudication (for the record)

Verified against worktree `feat/rbac-roles`:
- ❌ **FALSE (stale checkout):** "session-guard doesn't exist / all `/api/*` unauthenticated" — `_session_guard` exists at `app.py:182`; funnel endpoints gated. Real kernel folded into §6 (ingest auth model).
- ❌ **FALSE (stale checkout):** "live path hardcodes `telegramSubscribers`/`purchaseRevenueUsd`=0" — `telegramSubscribers` joined at `dashboard_service.py:277`; revenue computed (just zero data pre-Phase-4). Real kernel = Phase 4 feeds payment amounts.
- ✅ **CONFIRMED:** secret fail-open (`funnel.py:27`), `extract_visitor_id` `text[:64]` (`chatplace_events.py:112`), raw-row PII passthrough (`bitrix_client.py:112`), no-dedup append-only JSONL, whole-file rescan in request path, `min(100)` clamp. All addressed above.
- ⚠️ **Separate audit (not this spec):** `telegram_command_allowed` (`telegram_service.py:117`) alleged fail-open — it gates **live Meta writes**; verify independently.

## 10. Out of scope

- Real VSL watch-depth (self-hosted player) — proxy only for now.
- Per-visitor attribution into the bot (ChatPlace platform limit).
- Per-creative/adset ROAS (campaign-level ceiling).
- Multi-pipeline Bitrix.
- The separate `telegram_command_allowed` audit.
- Deployment (separate, requires explicit operator authorization).

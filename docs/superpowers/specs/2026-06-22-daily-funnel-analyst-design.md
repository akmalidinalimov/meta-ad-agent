# Daily Funnel Analyst — Design Spec

- **Date:** 2026-06-22
- **Status:** Approved design (pre-plan)
- **Branch:** feat/live-simple-dashboard
- **Owner:** Akmalidin / operator (shahlo.alikhanova@gmail.com)

## 1. Problem & goal

The Meta Ad Agent is currently a monitor + 4-hourly KPI digest. The operator wants it to
become a **proactive daily funnel analyst**: every day at **18:00 Europe/Stockholm** it
pulls fresh data, ranks **audiences (ad sets)** and **creatives (ads)** by progress toward
the operator's goal, and sends a **brief "where we are / what to do next" Telegram report**
with **one-tap-approve** actions.

**North-star goal (operator-chosen): quality over volume.** Prioritize the audiences and
creatives whose leads actually fill the form and buy, even at a higher cost-per-lead. Every
recommendation is judged against this goal and the operator's `targets_store` thresholds.

## 2. Decisions (locked)

1. **Goal:** quality > volume (most qualified leads / sales).
2. **Autonomy:** recommend + **one-tap approve**. The agent never changes the live ad
   account silently; it proposes, the operator taps Approve.
3. **Sequencing:** Approach A — ship the daily report now on what's measurable, wire true
   per-audience quality attribution in parallel; the report auto-upgrades proxy → real.
4. **Add-ons in scope:** (a) creative-fatigue/frequency alerts, (b) auto-exclude past
   leads/clickers, (c) intra-day anomaly alerts. **Deferred:** weekly Monday deep-dive.

## 3. Measurement reality (the constraint that shapes everything)

| Signal | Granularity available NOW | Source |
|---|---|---|
| Lead **volume** (CTA→bot "lead" action) | per ad, ad set, campaign | Meta insights `actions` |
| Engagement quality proxies (CTR, frequency, CPM, video hold p25–p100, avg watch) | per ad, ad set | Meta insights |
| Visit / lead / START rates | account + per **campaign** | funnel_events + Meta |
| Bot START | per **campaign** only (per-campaign referral links) | `telegram_starts_by_campaign_date` |
| Real form-fill (CRM lead) | **account only — no audience/creative key** (0/565 carry one) | Bitrix |
| Sale + amount (ROAS) | account only, and only if CRM stage+amount read | Bitrix |

**Consequence:** "which audience brings the highest-**quality** leads" is **not answerable
per ad set / creative today**. Phase 1 uses an engagement **proxy** for quality and is
explicitly labelled as such. Phase 2 (attribution) makes it real. Per-creative quality is
never CRM-attributable until per-ad attribution exists (out of near-term scope); per-creative
reporting stays volume + engagement only.

## 4. Architecture & components (all additive; fits existing patterns)

| Concern | Module | New / extend |
|---|---|---|
| 18:00 trigger | extend `_monitoring_loop` (backend/app.py) to poll a new `daily_analysis_scheduler.py` (own once-per-day debounce + run-log, mirroring `monitoring_scheduler`); add `POST /api/analysis/daily` (auth-guarded) as external-cron fallback | extend + new |
| Data pull | new `daily_analyst.py` — orchestrates fresh reads from `meta_client`, `funnel_events`/`funnel_history`, `bitrix_client` (read-only), `vsl`, `targets_store` | new |
| Metrics + ranking | new `audience_creative_metrics.py` — pure functions, unit-tested | new |
| Decision engine | new `daily_recommendations.py` — pure functions, unit-tested | new |
| Report builder | extend `telegram_digest.py` (new daily-analyst section) | extend |
| Delivery | reuse `telegram_outbound.py` | reuse |
| One-tap actions | extend existing pending-approval/suggestions flow; execute via `meta_client.update_ad` / `update_ad_set` / custom-audience write; gated by `META_LIVE_WRITES_ENABLED` + owner/admin role | extend |

Design for isolation: data collection, metric math, decision logic, and report formatting
are four separate units with explicit interfaces (collect → metrics → decisions → report),
each independently testable with synthetic inputs.

## 5. Data collection (`daily_analyst.py`)

For the **current day in the ad-account timezone** (so numbers match Ads Manager), plus a
trailing 3-day context window for trend confirmation:

- **Meta:** ad-level insights (`get_insights(level="ad")` / per-campaign `get_entity_insights`
  to dodge the account-wide ad page cap), ad-set insights, ad-set targeting/audience names
  (`get_ad_sets`), creative names (`get_ads`). Per-campaign conversion event resolved via the
  existing `_campaign_event_map` (promoted_object.custom_event_type) so each campaign's own
  optimization event is counted, not a hard-coded `lead`.
- **First-party funnel:** `count_event_users` / `telegram_starts_by_campaign_date` /
  `funnel_history` for visit, lead, START per campaign.
- **CRM (read-only):** `fetch_bitrix_leads` + `split_by_cell` for today's leads/stages
  (account-level; best-effort).
- **VSL:** current view count.
- **Targets:** `targets_store.load_targets()` for the ✅/⚠️ markers and goal-gating.

All reads best-effort: a failing source degrades that section, never blanks the report.

## 6. Metrics & ranking (`audience_creative_metrics.py`)

- **All rates** (account + per campaign): visit, lead, START, VSL-watch, CRM-fill, plus
  CPL / cost-per-START / CPM / CTR / frequency.
- **Per ad set (audience):** volume (own conversion event), cost-per-result, and a
  **quality score**:
  - **Phase 1 (proxy, 0–100):** weighted blend of video hold-rate (p75/p100), CTR→landing,
    inverse frequency, and per-campaign START rate. Labelled `quality*` = proxy.
  - **Phase 2 (real):** per-audience form-fill rate / cost-per-real-lead / cost-per-sale.
- **Per ad set → top-5 creatives** by the goal metric, with **underperformer flags**:
  high spend + zero/low leads past a data-sufficiency floor, low CTR, high frequency
  (fatigue), low video hold.

## 7. Decision engine (`daily_recommendations.py`)

Emits a list of recommendations, each = `{action, target, rationale, goalLink, confidence,
expectedImpact}`. Action types: `pause_creative`, `refresh_creative`, `prioritize_audience`
(budget shift up), `downweight_audience`, `exclude_past_leads`, `leave_and_test`.

Rules (quality-over-volume, learning-phase aware):
- **Learning-phase guardrail:** while a campaign is young / under the data-sufficiency floor
  (min impressions + spend) or lacking a 2–3-day confirming trend, prefer `leave_and_test`
  with an explicit "watch this" metric — never a knee-jerk cut that resets learning.
- **Quality tie-break:** a cheaper-but-shallow audience loses to a pricier-but-deep one;
  recommend shifting budget toward the higher-quality audience.
- **Cut creative:** only on high spend + ~zero leads past the floor + (fatigue/old) → pause
  to free budget for other creatives.
- **Refresh:** frequency over threshold or CTR decay across trailing days (quality-decay
  signature).
- **Exclude past leads/clickers** when re-serving non-converters is detected.
- Confidence reflects data sufficiency; low-confidence items are framed as "watch", not "do".

## 8. Daily report (extend `telegram_digest.py`)

Brief, layered, honest. Sections: **WHERE WE ARE** (today's spend/leads/CPL/START/CRM-fill
vs targets with ✅/⚠️, plus a learning-phase note) → **AUDIENCES** (ranked by quality score
then volume) → **TOP/BOTTOM CREATIVES** (top-5 per audience + flags) → **WHAT TO DO NEXT**
(top 1–3 actions, each with `[Approve] [Skip]`) → dashboard link for full detail. A footnote
marks `quality*` as a proxy until attribution is live. (See sample in the brainstorm thread.)

## 9. One-tap action / approval layer

Inline buttons create a **pending action** (extends the existing suggestions/pending flow).
On Approve (owner/admin only), execute the write via `meta_client` (`update_ad` pause,
`update_ad_set` budget) or a custom-audience exclusion — gated by `META_LIVE_WRITES_ENABLED`.
Every action is logged (audit trail) and confirmed back in Telegram. Skip dismisses it.

## 10. Add-ons

- **Creative-fatigue/frequency alerts:** part of the decision engine (`refresh_creative`).
- **Auto-exclude past leads/clickers:** `exclude_past_leads` one-tap action → create/update a
  Meta custom-audience exclusion so spend stops re-serving non-converters.
- **Intra-day anomaly alerts:** added to the existing 4-hourly monitoring path — CPL spike
  ≥2×, zero-result spend, or lead flatline → immediate Telegram ping (not held to 18:00).

## 11. Scheduling & timezone

- Fire at **18:00 Europe/Stockholm** via `zoneinfo` (DST-safe), polled by `_monitoring_loop`;
  `daily_analysis_scheduler` keeps a once-per-day run-log debounce so a restart near 18:00
  can't double-send.
- Meta "today" uses the **ad-account timezone** so the report matches Ads Manager; stated in
  the report.

## 12. Error handling & idempotency

- Per-source best-effort with a degraded-section note; whole-job failure sends a short
  "analysis failed, retrying" alert and logs the traceback.
- Daily run-log prevents duplicate sends.

## 13. Memory safety

Runs once daily, in-process, under the 550 MB cgroup cap. Single pass over `funnel_events`;
reuse the append-only / single-read patterns. Must not reintroduce the per-request
full-history reparse class of leak (ref: 2026-06-21 wedge).

## 14. Testing strategy

- Pure metric + decision functions unit-tested on synthetic insight rows (mirror
  `test_campaigns_api` patterns: patch `get_insights`/`get_entity_insights`/`get_ad_sets`).
- Report-format tests (mirror `test_telegram_digest`): section presence, target markers,
  proxy footnote, action buttons.
- Scheduler-gate test: fires once at/after 18:00 Stockholm, debounce holds.
- No live Meta/Bitrix calls in tests.

## 15. Phasing

- **Phase 1 (this build):** scheduler + collection + metrics (proxy quality) + decision
  engine + report + one-tap approve + the 3 add-ons. Daily reports start on deploy.
- **Phase 2 (parallel, partly operator-gated on ChatPlace):** per-ad-set referral links →
  in-bot capture → `crm_form_submit` carrying audience → real per-audience quality +
  cost-per-sale. Report auto-upgrades; no rebuild.

## 16. Out of scope (YAGNI for now)

Weekly Monday deep-dive; dayparting automation; per-creative CRM attribution; ask-the-agent
metric drill-down; cost-per-sale automation (lands with Phase 2 CRM stage+amount).

## 17. Risks / open items

- Per-audience quality is a proxy until Phase 2 — must never be presented as real.
- Ad-account TZ vs Stockholm schedule TZ: "today" boundaries differ; report states which.
- Live writes depend on `META_LIVE_WRITES_ENABLED` + role; if disabled, actions show as
  "manual" (copy/paste instructions) instead of executable buttons.
- Custom-audience exclusion write path must be verified against the live API before enabling.

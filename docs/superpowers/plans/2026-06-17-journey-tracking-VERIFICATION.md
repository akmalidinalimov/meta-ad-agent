# Journey Tracking — Verification Evidence

Branch: `feat/journey-tracking` · Staging: local backend on `:8001` · Bitrix: READ-ONLY (`crm.lead.list`, `crm.deal.list`, `crm.status.list` only). Live `:8000` (OCI VM), the Meta campaign, and the live bot flow were not touched.

## Backend tests
- `python -m pytest backend/ -q` → **183 passed** (includes all pre-existing CRM/chatplace/funnel tests — additive, no regressions).
- New: `backend/test_crm_funnel.py` (8), `backend/test_crm_funnel_api.py` (2), extended `test_bitrix_client.py` (paging/date-filter/deals), `test_chatplace_events.py` (aud/phone capture).

## Live read of `GET /api/crm/funnel?days=30` (entity=lead) — 2026-06-17
- `ok: true`, `source: "bitrix"`, real read of the production portal.
- **177 leads** in the last 30 days, distributed across the **real, dynamically discovered** lead stage model (no hardcoding):
  - NEW "Ne obrabotinniy", UC_7CA0VJ "Lead" (94), PROCESSED "Javob bermadi" (30), IN_PROCESS "O'ylab ko'radi" (12), UC_1FIBKP "Telegram" (10), UC_VUJHS2 "Ma'lumot Berildi" (10), JUNK "Некачественный лид" (10), UC_3Y9MU5 "To'lov Kutilvoti" (5), UC_8Y6Y8I "Qayta aloqa" (3), CONVERTED "Качественный лид" (2), UC_VGKL54 "Onlinedagilar uchun" (1).
  - Heuristic-detected paid lead stages: `UC_5W2670` "Webinar to'lov", `UC_IEO03L` "Webinar to'lov Tasdiqlandi", `UC_QZUVRV` "Bo'lib To'lash".
- `matchRate: 0.0`, **all 177 leads in `unattributed`** — CORRECT: the enriched bot-start webhook (Part 3.1) is not applied/flowing yet, so no `aud`/`phone` bot-start events exist to phone-join against. The per-audience split lights up automatically once the START webhook sends `aud`+`phone` and those users appear as Bitrix leads. Honest reporting, nothing hidden.

## Live read of `entity=deal` — 2026-06-17
- Deal pipeline discovered: NEW "YANGI IMKONIYAT" → UC_AE3000 "FIRST CALL LEAD" → UC_KTU86M "ALOQA YO'Q" → PREPARATION "ALOQA O'RNATILDI" → PREPAYMENT_INVOICE "TAKLIF YUBORILDI" → EXECUTING "KELISHUV" → **WON "SOTILDI"** / LOSE "ARXIV".
- **0 deals in the last 30 days** → current sales activity is tracked on **Leads**, not Deals.

## Regression (live)
- `/api/crm/bitrix/status` → `{configured: true}` (unchanged).
- `/api/funnel/summary` → same key set as before (`totalEvents, eventsByName, eventsBySegment, uniqueVisitors, uniqueTelegramUsers, latestEventAt, eventSteps, rates, crm`).

## OPEN DECISION FOR THE USER (blocks the headline "Paid rate", not the build)
Where does **"Paid"** live for this business?
- **Lead path:** one of the payment lead-statuses (e.g. `UC_IEO03L` "Webinar to'lov Tasdiqlandi" = payment confirmed), or
- **Deal path:** deal stage `WON` ("SOTILDI" = Sold), once leads convert to deals.

Action: confirm with the sales team, then set `BITRIX_PAID_STATUS_IDS=<comma-separated status ids>` in backend env (authoritative; overrides the keyword heuristic). Use `?entity=deal` if Paid is tracked on the deal pipeline. Until set, the dashboard shows the heuristic's best guess and exposes `paidStageIds` so it is auditable.

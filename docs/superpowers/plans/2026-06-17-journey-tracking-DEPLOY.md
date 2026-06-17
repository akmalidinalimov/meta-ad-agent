# Journey Tracking — Cutover Runbook (live `:8000` on the OCI VM)

Branch: `feat/journey-tracking`. All changes are **additive and read-only against Bitrix**. The live `:8000` service, the Meta campaign, and the live bot flow are unaffected by merging code; the only behavior change is two new endpoints + one gated dashboard panel. Do the cutover at a **quiet hour (≈03:00–06:00 UZT)** with the previous build kept for rollback.

> I (Claude) cannot reach the OCI VM from this machine. These are the exact steps for you to run there (or for me to run if you give me VM access). **Nothing here has been deployed.**

## Pre-cutover (already done on the branch)
- Backend suite green: `python -m pytest backend/ -q` → 183 passed.
- Frontend: `npx tsc -b` clean, `npx vitest run` → 30 passed.
- Staging verified on local `:8001` against **live Bitrix read-only**: `/api/crm/funnel?days=30` → 200, 177 leads, real stage model discovered, `matchRate 0` (no enriched bot-starts yet — expected). See `2026-06-17-journey-tracking-VERIFICATION.md`.

## What ships
- New, additive: `GET /api/crm/funnel?days=N&entity=lead|deal`, capture of `aud`+`phone` on `/api/chatplace/events`, `CrmFunnelByAudience` dashboard panel (gated by `VITE_CRM_ENABLED`).
- Untouched: every existing endpoint/response shape, the auth layer, the ingest exemptions (`/api/chatplace/events`, `/api/funnel/events`).

## Backend cutover (VM)
1. `cd <repo on VM>` and fetch: `git fetch origin && git log --oneline origin/feat/journey-tracking -7`.
2. **Port additively, preserving the deployed auth layer + ingest exemptions** (the deployed code diverges from the repo). Either cherry-pick the 6 feature commits (after the `ee9ab06` baseline) onto the live branch, or merge `feat/journey-tracking` and re-apply the deploy-only auth changes. Confirm `/api/chatplace/events` and `/api/funnel/events` remain auth-exempt.
3. Set the Paid-stage env on the VM backend env (matches the "combined" choice):
   `BITRIX_PAID_STATUS_IDS=UC_5W2670,UC_IEO03L,UC_QZUVRV`
4. Restart the `:8000` uvicorn service.
5. Smoke test (read-only):
   - `curl -s 'http://127.0.0.1:8000/api/crm/funnel?days=30' | head` → `ok:true`, stages + audiences + `unattributed` + `matchRate`.
   - Regression: `/api/funnel/rates?days=30`, `/api/dashboard`, `/api/crm/bitrix/status` return their **previous shapes**.

## Frontend cutover
- Build with the flag on: `VITE_CRM_ENABLED=true VITE_API_BASE_URL=<prod api base> npm run build`, deploy `dist/`.
- With the flag off (or unset) the panel does not render — safe partial-ship default.

## Rollback (instant)
- Backend: keep the previous commit/build; `git checkout <prev> && restart uvicorn`. The new endpoints simply disappear; nothing else changes.
- Frontend: redeploy the previous `dist/`, or rebuild with `VITE_CRM_ENABLED` unset to hide the panel without a code change.

## Manual prerequisite to make attribution actually flow (ChatPlace UI — your step, live flow)
Until this is applied, every lead stays in `unattributed` (matchRate 0) by design. In the bot START flow's **External Request** node, set the POST body to:
```json
{ "event_name":"bot_start", "telegram_user_id":"{{clientId}}",
  "aud":"{{aud}}", "username":"{{username}}", "phone":"{{Phone}}", "ts":"{{createdAt}}" }
```
Confirm `{{aud}}` resolves on a real new-account start (Part 1.2). Once `aud`+`phone` flow and those users appear as Bitrix leads, the phone-join lights up the per-audience split automatically — no code change.

## Open follow-ups (not blocking)
- Optional Part 3.4 daily snapshot + per-audience movement trend (Task 12 — deferred).
- If "Paid" should later mean a closed **Deal** (`WON`/"SOTILDI") instead of the lead payment statuses, switch the dashboard to `?entity=deal` and set `BITRIX_PAID_STATUS_IDS=WON`.

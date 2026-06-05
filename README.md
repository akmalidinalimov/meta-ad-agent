# Meta Ad Agent

Dashboard and agent foundation for auditing Meta ads, creatives, audiences, placements, and funnel quality from Meta click through Telegram, webinar, and purchase.

## Current State

- React/TypeScript dashboard with navigation, filters, creative detail, tracking health, alerts, experiments, and glossary.
- FastAPI backend with `/api/dashboard` and `/api/health`.
- Frontend fetches `/api/dashboard` first and falls back to local mock data if the backend is unavailable.
- Data model is ready for Meta, landing page, Telegram, webinar, YouTube, and creative-analysis integrations.

## Run Locally

Install frontend dependencies:

```bash
npm install
```

Install backend dependencies:

```bash
python -m pip install -r backend/requirements.txt
```

Start the backend:

```bash
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Start the frontend:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173
```

## Deploy as a single unit

In production the FastAPI backend **also serves the built React/Vite SPA**, so the
whole app ships as one same-origin container — no separate frontend host, no CORS or
base-URL juggling (`apiUrl()` returns relative `/api/...` when not on localhost).

Build the frontend, then run the backend — it picks up `dist/` automatically:

```bash
npm run build                                  # produces dist/
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` — the UI and the API are served from the same origin.
(If `dist/` is absent the backend still runs API-only, e.g. for `npm run dev`.)

### Container / cloud (one command)

A multi-stage `Dockerfile` builds `dist/` and runs the backend that serves it:

```bash
docker build -t meta-ad-agent .
docker run --rm -p 8000:8000 --env-file .env meta-ad-agent
```

The bundled `render.yaml` is a Render Blueprint; the same `Dockerfile` deploys
directly on Railway and Fly.io. The platform injects `$PORT`; uvicorn binds to it.

**Deploy on Render (one path):** push this branch to GitHub → New → Blueprint →
pick the repo (Render reads `render.yaml`) → set the secret env vars it prompts for
(`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, `META_PIXEL_ID`, `OPENAI_API_KEY`, and
`FUNNEL_ALLOWED_ORIGINS` = your Render URL). `META_LIVE_WRITES_ENABLED` stays `false`
and `AGENT_API_KEY` is generated for you. Railway/Fly: point the service at the
`Dockerfile` and set the same env vars.

### Smoke-test after deploy

Against the live URL (replace `$APP`):

1. `curl https://$APP/api/health` → `{"status":"ok"}`.
2. Open `https://$APP/` → the chat front door loads; the browser console shows **no**
   CORS errors (same-origin) and no "backend unreachable" banner.
3. Send a chat message (or click a starter prompt) → the agent replies.
4. With `META_LIVE_WRITES_ENABLED=false`, draft a campaign and dry-run an approval:
   the "Create paused campaign in Meta" button is **disabled with a reason** — confirming
   no live write can happen.
5. Check the platform logs: request lines do **not** contain `access_token=` (the
   HTTP-client loggers are quieted so the Meta token never reaches logs).

### Configuration

Copy `.env.example` to `.env` and set the values you need. Deployment-relevant flags:

| Variable | Default | Purpose |
| --- | --- | --- |
| `META_LIVE_WRITES_ENABLED` | `false` | Master kill-switch for live Meta writes — keep `false` until trusted. |
| `AGENT_API_KEY` | _(unset)_ | When set, non-GET requests must send a matching `X-API-Key` header. Set it in any hosted deploy. |
| `META_PIXEL_ID` | _(unset)_ | Conversions pixel for `OFFSITE_CONVERSIONS` ad sets. |
| `FUNNEL_ALLOWED_ORIGINS` | localhost dev | Comma-separated allowed origins (same-origin deploys need only your own URL). |
| `MONITORING_SCHEDULER_ENABLED` | `false` | Runs the in-process 4-hourly monitoring loop. Prefer an external cron in production. |

**Browser access protection (single operator):** `AGENT_API_KEY` protects programmatic
(non-GET) callers, but it is not a login for the UI. Put the whole app behind a
platform access layer (Cloudflare Access, the host's password protection, or basic-auth
at the proxy) so the operator console isn't exposed publicly. Keep
`META_LIVE_WRITES_ENABLED=false` until the live-write path is trusted.

## Make the agent proactive (go live)

The dashboard + chat work as soon as the Meta account is synced. To get the agent
**watching every 4 hours and reasoning from real downstream quality** (Telegram START,
website visit→lead), connect the funnel signals and turn the loop on. The event
ingestion is already built — see `docs/FUNNEL_EVENT_TRACKING.md` for exact payloads.

1. **Track the website.** Drop `public/landing-tracker.js` on each landing page and set
   `window.MetaAdAgentTracker = { endpoint: 'https://<your-app>/api/funnel/events', segment, vslId }`.
   It emits `landing_view` / `telegram_link_click` / `form_button_click` with campaign
   attribution and a persistent `visitorId`, and decorates the Telegram CTA with
   `?start=<visitorId>`. Add your landing domains to `FUNNEL_ALLOWED_ORIGINS`.
2. **Connect the Telegram bot START.** Configure the bot / ChatPlace automation to POST a
   `bot_start` event to `https://<your-app>/api/chatplace/events`, passing the `start`
   payload (the visitor) plus the `campaign_id`. This lights up Telegram START per campaign
   — the account's primary success metric and the trigger for the high-severity quality
   alarm. Set `CHATPLACE_WEBHOOK_SECRET`.
3. **Turn on the 4-hourly loop.** Either set `MONITORING_SCHEDULER_ENABLED=true` (in-process)
   or point an external scheduler at `POST /api/monitoring/scheduled` every hour (preferred —
   it keeps its own 4-hour debounce). Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_CHAT_ID`
   and register the bot webhook so suggestions arrive in Telegram with **Approve / Reject /
   Needs-changes** buttons (and in the web chat).
4. **Verify go-live.** Send one real `bot_start`; `GET /api/funnel/summary` shows it and
   `telegramStartRate`. Trigger `POST /api/monitoring/scheduled` over two days of data and
   confirm an alert reaches Telegram. Tap **Approve** in Telegram and confirm the approval
   is recorded (execution stays a separate, guarded step while `META_LIVE_WRITES_ENABLED=false`).

> Not yet wired: purchase/ROAS (no payments tracked yet — the agent honestly uses the
> Telegram-START + lead-quality proxy until a `full_payment` event or CRM won-deal is
> connected) and auto-execution (approvals are recorded, not auto-applied). Both are
> documented follow-ups.

## API

Health:

```text
GET /api/health
```

Dashboard data:

```text
GET /api/dashboard
```

## Next Build Step

Add a read-only Meta Marketing API importer:

1. Store Meta settings in environment variables.
2. Pull campaigns, ad sets, ads, creatives, and insights.
3. Normalize Meta responses into the existing dashboard model.
4. Keep writes disabled until the audit layer is reliable.

## Meta Connection

Create a local `.env` file from `.env.example`:

```bash
copy .env.example .env
```

Fill these values locally:

```env
META_ACCESS_TOKEN=your_meta_token
META_AD_ACCOUNT_ID=act_your_ad_account_id
META_BUSINESS_ID=your_business_id
META_API_VERSION=v23.0
META_PIXEL_ID=your_pixel_id_if_available
```

Do not commit `.env`. It is ignored by Git.

Check connection:

```text
http://127.0.0.1:8000/api/meta/status
```

Once connected, campaign reads will be available at:

```text
http://127.0.0.1:8000/api/meta/campaigns
```

## Quality Checks

Before pushing a dashboard change, run the checklist in `docs/QA_CHECKLIST.md`.

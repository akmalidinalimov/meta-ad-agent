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

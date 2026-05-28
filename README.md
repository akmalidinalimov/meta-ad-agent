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

# Dashboard QA Checklist

Run this before pushing dashboard changes.

## Commands

- `npm test`
- `npm run lint`
- `npm run build`
- `python -m pytest backend -q`

## Manual Checks

- 7/30/90 day filter only shows campaigns active inside that window.
- Multi-campaign selection updates all KPIs, charts, funnel, placements, and creative rankings.
- A campaign with no metric rows shows a clear empty state and a reset button.
- Creative table is ranked by quality score and starts at rank 1.
- Creative thumbnails render when available.
- A play marker appears only when `videoUrl` exists.
- Agent chat gives one answer per question and shows sources.
- Agent chat shows the routed specialist when the orchestrator handles sub-agent, campaign planning, or execution-safety questions.
- A complete campaign brief in chat creates a draft playbook and does not execute Meta changes.
- `GET /api/agents` returns every configured specialist and confirms live execution is disabled.
- Meta connection status never exposes access tokens.
- Settings can run either a 90-day or 180-day Meta sync.
- Saved snapshots appear in Settings after a successful sync.
- Campaign playbooks are configurable and not fixed to three VSL segments.
- Strategy view can prepare an execution approval request from a saved playbook.
- Approval queue shows stored execution approvals with guardrail status and paused campaign/ad set preview.
- Approving an execution request enables dry-run only; dry-run confirms no request was sent to Meta.
- Live Meta write execution remains disabled until a separately approved release.
